#!/usr/bin/env python3
"""Infer Codex activity from local rollout JSONL session files."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SESSIONS_ROOT = Path.home() / ".codex" / "sessions"
TAIL_BYTES = 1_500_000
FILE_SCAN_INTERVAL_SECONDS = 1.5
RECENT_FILE_WINDOW_SECONDS = 24 * 60 * 60
ACTIVE_STALE_SECONDS = 15 * 60
MAX_WATCHED_FILES = 24
COMPLETION_EVENT_TYPES = {
    "agent_done",
    "abort",
    "aborted",
    "cancel",
    "canceled",
    "cancelled",
    "interrupted",
    "manual_stop",
    "stop",
    "stopped",
    "task_complete",
    "turn_aborted",
    "turn_canceled",
    "turn_cancelled",
}
COMPLETION_STATUSES = {
    "abort",
    "aborted",
    "cancel",
    "canceled",
    "cancelled",
    "complete",
    "completed",
    "done",
    "interrupted",
    "stopped",
}
TURN_STATUS_EVENT_TYPES = {
    "agent_state",
    "run_state",
    "task_state",
    "turn_state",
}


def status_priority(status: str) -> int:
    return {"red": 0, "green": 1, "yellow": 2}.get(status, 0)


def parse_json_line(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


@dataclass
class RolloutFileState:
    path: Path
    offset: int = 0
    is_subagent: bool = False
    parent_thread_id: str | None = None
    status: str = "red"
    last_update_ts: float = 0.0
    last_event_type: str | None = None
    last_payload_type: str | None = None
    last_reason: str = "initial"
    saw_final: bool = False


class CodexRolloutStatus:
    def __init__(self, sessions_root: Path = DEFAULT_SESSIONS_ROOT) -> None:
        self.sessions_root = sessions_root
        self.files: dict[Path, RolloutFileState] = {}
        self.watched_paths: list[Path] = []
        self.last_scan_ts = 0.0
        self.last_error: str | None = None
        self.last_snapshot: dict[str, Any] = self.snapshot("red", "rollout:init")

    def refresh(self) -> dict[str, Any]:
        current = time.time()
        self.last_error = None
        if current - self.last_scan_ts >= FILE_SCAN_INTERVAL_SECONDS:
            self._rescan_files(current)
        for path in list(self.watched_paths):
            self._read_new_lines(path)
        self._cleanup(current)
        self.last_snapshot = self._aggregate()
        return self.last_snapshot

    def _rescan_files(self, current: float) -> None:
        self.last_scan_ts = current
        if not self.sessions_root.exists():
            self.watched_paths = []
            return
        cutoff = current - RECENT_FILE_WINDOW_SECONDS
        candidates: list[tuple[float, Path]] = []
        try:
            for path in self.sessions_root.rglob("rollout-*.jsonl"):
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if mtime >= cutoff:
                    candidates.append((mtime, path))
        except OSError as exc:
            self.last_error = str(exc)
            self.watched_paths = []
            return
        candidates.sort(reverse=True)
        self.watched_paths = [path for _, path in candidates[:MAX_WATCHED_FILES]]
        watched = set(self.watched_paths)
        for old_path in list(self.files):
            if old_path not in watched:
                self.files.pop(old_path, None)
        for path in self.watched_paths:
            if path not in self.files:
                state = RolloutFileState(path=path, offset=self._initial_offset(path))
                self._load_session_metadata(state)
                self.files[path] = state

    def _initial_offset(self, path: Path) -> int:
        try:
            size = path.stat().st_size
        except OSError:
            return 0
        return 0 if size <= TAIL_BYTES else max(0, size - TAIL_BYTES)

    def _load_session_metadata(self, state: RolloutFileState) -> None:
        try:
            with state.path.open("r", encoding="utf-8", errors="replace") as handle:
                first_line = handle.readline()
        except OSError:
            return
        item = parse_json_line(first_line)
        if item is not None and item.get("type") == "session_meta":
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            self._apply_session_metadata(state, payload)

    def _apply_session_metadata(self, state: RolloutFileState, payload: dict[str, Any]) -> None:
        parent_thread_id = payload.get("parent_thread_id")
        if isinstance(parent_thread_id, str) and parent_thread_id:
            state.is_subagent = True
            state.parent_thread_id = parent_thread_id

    def _read_new_lines(self, path: Path) -> None:
        state = self.files.get(path)
        if state is None:
            return
        try:
            size = path.stat().st_size
            if size < state.offset:
                state.offset = 0
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(state.offset)
                for raw_line in handle:
                    item = parse_json_line(raw_line)
                    if item is not None:
                        self._handle_item(state, item)
                state.offset = handle.tell()
        except OSError as exc:
            self.last_error = str(exc)

    def _handle_item(self, state: RolloutFileState, item: dict[str, Any]) -> None:
        event_type = str(item.get("type") or "")
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        payload_type = str(payload.get("type") or "")
        event_ts = self._timestamp_to_epoch(item.get("timestamp")) or time.time()

        if event_type == "session_meta":
            self._apply_session_metadata(state, payload)
            return

        if self._is_completion_event(event_type, payload):
            self._record_event(state, event_type, payload_type, event_ts)
            state.status = "red"
            state.saw_final = True
            state.last_reason = f"{event_type}:{payload_type or 'complete'}"
            return

        if self._is_active_event(event_type, payload_type, payload):
            self._record_event(state, event_type, payload_type, event_ts)
            state.status = "green"
            state.saw_final = False
            state.last_reason = f"{event_type}:{payload_type or payload.get('phase') or 'active'}"

    def _record_event(self, state: RolloutFileState, event_type: str, payload_type: str, event_ts: float) -> None:
        state.last_event_type = event_type
        state.last_payload_type = payload_type
        state.last_update_ts = event_ts

    def _is_active_event(self, event_type: str, payload_type: str, payload: dict[str, Any]) -> bool:
        if event_type == "response_item":
            if payload_type in {
                "reasoning",
                "function_call",
                "function_call_output",
                "custom_tool_call",
                "custom_tool_call_output",
                "web_search_call",
            }:
                return True
            if payload_type == "message" and payload.get("phase") == "commentary":
                return True
        if event_type == "event_msg":
            msg_type = str(payload.get("type") or "")
            return msg_type in {
                "agent_message",
                "patch_apply_begin",
                "patch_apply_end",
                "task_started",
                "web_search_end",
                "tool_call_begin",
                "tool_call_end",
            } and payload.get("phase") != "final"
        return False

    def _is_completion_event(self, event_type: str, payload: dict[str, Any]) -> bool:
        if event_type == "event_msg":
            msg_type = str(payload.get("type") or "").lower()
            phase = str(payload.get("phase") or "").lower()
            status = str(payload.get("status") or "").lower()
            reason = str(payload.get("reason") or "").lower()
            status_is_turn_level = bool(status in COMPLETION_STATUSES and msg_type in TURN_STATUS_EVENT_TYPES)
            return (
                msg_type in COMPLETION_EVENT_TYPES
                or phase == "final"
                or status_is_turn_level
                or reason in COMPLETION_EVENT_TYPES
            )
        if event_type != "response_item":
            return False
        if payload.get("type") != "message" or payload.get("role") != "assistant":
            return False
        phase = payload.get("phase")
        return phase == "final" or phase is None

    def _cleanup(self, current: float) -> None:
        stale_before = current - ACTIVE_STALE_SECONDS
        for state in self.files.values():
            if state.status == "green" and state.last_update_ts and state.last_update_ts < stale_before:
                state.status = "red"
                state.last_reason = "active-stale-timeout"

    def _aggregate(self) -> dict[str, Any]:
        active = [state for state in self.files.values() if state.status == "green"]
        top_level_active = [state for state in active if not state.is_subagent]
        if active:
            latest = max(active, key=lambda item: item.last_update_ts)
            return self.snapshot(
                "green",
                latest.last_reason,
                active_count=len(top_level_active),
                source_path=latest.path,
                source_event=latest.last_event_type,
                source_payload=latest.last_payload_type,
                active_sources=active,
                raw_active_count=len(active),
                subagent_active_count=len(active) - len(top_level_active),
            )
        latest_any = max(self.files.values(), key=lambda item: item.last_update_ts, default=None)
        return self.snapshot(
            "red",
            latest_any.last_reason if latest_any else "no-rollout-files",
            active_count=0,
            source_path=latest_any.path if latest_any else None,
            source_event=latest_any.last_event_type if latest_any else None,
            source_payload=latest_any.last_payload_type if latest_any else None,
            raw_active_count=0,
            subagent_active_count=0,
        )

    def snapshot(
        self,
        status: str,
        reason: str,
        active_count: int = 0,
        source_path: Path | None = None,
        source_event: str | None = None,
        source_payload: str | None = None,
        active_sources: list[RolloutFileState] | None = None,
        raw_active_count: int = 0,
        subagent_active_count: int = 0,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "source": "rollout",
            "reason": reason,
            "active_count": active_count,
            "raw_active_count": raw_active_count,
            "subagent_active_count": subagent_active_count,
            "source_path": str(source_path) if source_path else None,
            "source_event": source_event,
            "source_payload": source_payload,
            "watched_count": len(self.watched_paths),
            "sessions_root": str(self.sessions_root),
            "error": self.last_error,
            "active_sources": [
                {
                    "path": str(item.path),
                    "reason": item.last_reason,
                    "event": item.last_event_type,
                    "payload": item.last_payload_type,
                    "last_update_ts": item.last_update_ts,
                    "is_subagent": item.is_subagent,
                    "parent_thread_id": item.parent_thread_id,
                }
                for item in (active_sources or [])
            ],
        }

    def _timestamp_to_epoch(self, value: Any) -> float | None:
        if not isinstance(value, str):
            return None
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return dt.datetime.fromisoformat(value).timestamp()
        except ValueError:
            return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Codex rollout-derived status.")
    parser.add_argument("--sessions-root", type=Path, default=DEFAULT_SESSIONS_ROOT)
    args = parser.parse_args()

    status = CodexRolloutStatus(args.sessions_root).refresh()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
