#!/usr/bin/env python3
"""Codex hook target for the portable traffic-light indicator."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

try:
    import msvcrt
except ImportError:  # pragma: no cover - Windows target, POSIX fallback is best effort.
    msvcrt = None


APP_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = APP_DIR / "runtime"
STATE_PATH = RUNTIME_DIR / "state.json"
EVENTS_PATH = RUNTIME_DIR / "events.jsonl"
LOCK_PATH = RUNTIME_DIR / "state.lock"
STALE_AFTER_SECONDS = 6 * 60 * 60

RUNNING_EVENTS = {"UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStart"}
WAITING_EVENTS = {"PermissionRequest"}
STOP_EVENTS = {"SessionStart", "Stop", "SubagentStop"}
ERROR_EVENTS = {"Error", "SessionError"}


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        corrupt = path.with_suffix(path.suffix + f".corrupt-{dt.datetime.now():%Y%m%d-%H%M%S}")
        try:
            path.replace(corrupt)
        except OSError:
            pass
        return default


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    Path(tmp_name).replace(path)


class FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        if msvcrt is not None:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_LOCK, 1)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle is None:
            return
        if msvcrt is not None:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        self.handle.close()


def read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw_stdin": raw[:4000]}


def get_nested(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def session_key(payload: dict[str, Any], explicit: str | None) -> str:
    if explicit:
        return explicit
    direct = get_nested(payload, "session_id", "sessionId", "conversation_id", "conversationId")
    if direct:
        return str(direct)
    cwd = get_nested(payload, "cwd", "workspace", "repo")
    if cwd:
        return f"cwd:{cwd}"
    return "default"


def tool_name(payload: dict[str, Any]) -> str | None:
    direct = get_nested(payload, "tool_name", "toolName", "tool", "matcher")
    if direct:
        return str(direct)
    tool = payload.get("tool_input")
    if isinstance(tool, dict):
        return str(get_nested(tool, "name", "tool_name") or "")
    return None


def state_for_event(event: str) -> str:
    if event in WAITING_EVENTS:
        return "waiting"
    if event in STOP_EVENTS:
        return "idle"
    if event in ERROR_EVENTS:
        return "waiting"
    if event in RUNNING_EVENTS:
        return "running"
    return "running"


def cleanup_stale_sessions(sessions: dict[str, Any], current_time: dt.datetime) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, item in sessions.items():
        if not isinstance(item, dict):
            continue
        status = item.get("status")
        updated_at = parse_time(item.get("updated_at"))
        if status in {"idle", "stopped"}:
            continue
        if updated_at and (current_time - updated_at).total_seconds() > STALE_AFTER_SECONDS:
            continue
        cleaned[key] = item
    return cleaned


def aggregate_status(sessions: dict[str, Any]) -> str:
    statuses = [item.get("status") for item in sessions.values() if isinstance(item, dict)]
    if any(status == "waiting" for status in statuses):
        return "yellow"
    if any(status == "running" for status in statuses):
        return "green"
    return "red"


def update_state(event: str, payload: dict[str, Any], explicit_session: str | None) -> dict[str, Any]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    current_iso = now_iso()
    current_dt = dt.datetime.now(dt.UTC)
    key = session_key(payload, explicit_session)
    next_status = state_for_event(event)

    with FileLock(LOCK_PATH):
        state = load_json(
            STATE_PATH,
            {
                "version": 1,
                "status": "red",
                "updated_at": current_iso,
                "reason": "initial",
                "sessions": {},
            },
        )
        sessions = state.get("sessions")
        if not isinstance(sessions, dict):
            sessions = {}
        sessions = cleanup_stale_sessions(sessions, current_dt)

        if next_status == "idle":
            sessions.pop(key, None)
        else:
            sessions[key] = {
                "status": next_status,
                "last_event": event,
                "tool": tool_name(payload),
                "turn_id": get_nested(payload, "turn_id", "turnId"),
                "cwd": get_nested(payload, "cwd"),
                "updated_at": current_iso,
            }

        state = {
            "version": 1,
            "status": aggregate_status(sessions),
            "updated_at": current_iso,
            "reason": event,
            "session_count": len(sessions),
            "sessions": sessions,
        }
        atomic_write_json(STATE_PATH, state)

        with EVENTS_PATH.open("a", encoding="utf-8") as events:
            event_record = {
                "at": current_iso,
                "event": event,
                "session": key,
                "status": state["status"],
                "tool": tool_name(payload),
            }
            events.write(json.dumps(event_record, ensure_ascii=False) + "\n")

    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Update the Codex traffic-light indicator state.")
    parser.add_argument("--event", required=True, help="Codex hook event name.")
    parser.add_argument("--session", help="Override session id, useful for manual tests.")
    parser.add_argument("--print-state", action="store_true", help="Print the updated state JSON.")
    args = parser.parse_args()

    payload = read_stdin_json()
    state = update_state(args.event, payload, args.session)
    if args.print_state:
        print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
