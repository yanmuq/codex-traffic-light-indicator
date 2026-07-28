#!/usr/bin/env python3
"""Infer Codex activity from the local logs SQLite database.

This is a fallback signal for cases where lifecycle hooks are not yet trusted,
not reloaded, or otherwise do not fire in the current Codex app process.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path.home() / ".codex" / "logs_2.sqlite"
RECENT_SCAN_SECONDS = 45 * 60
ACTIVE_STALE_SECONDS = 30 * 60
MAX_ROWS_PER_POLL = 6000

TURN_RE = re.compile(r"turn\.id=([0-9a-f-]+)")
THREAD_RE = re.compile(r"thread(?:_id|\.id)=([0-9a-f-]+)")
RESPONSE_RE = re.compile(r'"id":"(resp_[^"]+)"')

RUNNING_EVENTS = (
    '"type":"response.created"',
    '"type":"response.in_progress"',
)
STOP_EVENTS = (
    '"type":"response.completed"',
    '"type":"response.failed"',
    '"type":"response.cancelled"',
    '"type":"response.incomplete"',
)


def status_priority(status: str) -> int:
    return {"red": 0, "green": 1, "yellow": 2}.get(status, 0)


class CodexLogStatus:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.last_id = 0
        self.active_turns: dict[str, int] = {}
        self.last_error: str | None = None

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=0.2)

    def _event_key(self, body: str, prefer_response: bool) -> str | None:
        regexes = (RESPONSE_RE,) if prefer_response else (TURN_RE, THREAD_RE, RESPONSE_RE)
        for regex in regexes:
            match = regex.search(body)
            if match:
                return match.group(1)
        return None

    def _handle_row(self, row_id: int, ts: int, body: str) -> None:
        self.last_id = max(self.last_id, row_id)
        if any(marker in body for marker in RUNNING_EVENTS):
            key = self._event_key(body, prefer_response=True)
            if not key:
                return
            self.active_turns[key] = ts
            return

        if any(marker in body for marker in STOP_EVENTS):
            key = self._event_key(body, prefer_response=True)
            if not key:
                return
            self.active_turns.pop(key, None)

    def _cleanup(self, now_ts: int) -> None:
        stale_before = now_ts - ACTIVE_STALE_SECONDS
        self.active_turns = {
            key: ts for key, ts in self.active_turns.items() if ts >= stale_before
        }

    def refresh(self) -> dict[str, Any]:
        now_ts = int(time.time())
        self.last_error = None
        if not self.db_path.exists():
            return self.snapshot("red")

        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                if self.last_id <= 0:
                    cutoff = now_ts - RECENT_SCAN_SECONDS
                    rows = conn.execute(
                        """
                        select id, ts, feedback_log_body
                        from logs
                        where ts >= ?
                        order by id asc
                        limit ?
                        """,
                        (cutoff, MAX_ROWS_PER_POLL),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        select id, ts, feedback_log_body
                        from logs
                        where id > ?
                        order by id asc
                        limit ?
                        """,
                        (self.last_id, MAX_ROWS_PER_POLL),
                    ).fetchall()
        except Exception as exc:
            self.last_error = str(exc)
            return self.snapshot("red")

        for row in rows:
            body = row["feedback_log_body"] or ""
            self._handle_row(int(row["id"]), int(row["ts"]), body)

        self._cleanup(now_ts)
        if self.active_turns:
            return self.snapshot("green")
        return self.snapshot("red")

    def snapshot(self, status: str) -> dict[str, Any]:
        return {
            "status": status,
            "last_id": self.last_id,
            "active_count": len(self.active_turns),
            "active_turns": sorted(self.active_turns.keys()),
            "db_path": str(self.db_path),
            "error": self.last_error,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Codex log-derived status.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    status = CodexLogStatus(args.db).refresh()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
