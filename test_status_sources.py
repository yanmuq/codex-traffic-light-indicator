#!/usr/bin/env python3
"""Regression checks for the portable traffic-light status sources."""

from __future__ import annotations

import json
import tempfile
import time
import datetime as dt
from pathlib import Path

from codex_rollout_status import CodexRolloutStatus
from codex_status_hook import update_state
from indicator import (
    COMPLETION_BLINK_COUNT,
    COMPLETION_BLINK_HALF_PERIOD_SECONDS,
    COMPLETION_FLASH_SECONDS,
    DISPLAY_STATUS,
    HOOK_YELLOW_MAX_AGE_SECONDS,
    TrafficLightIndicator,
)


def write_line(path: Path, item: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def rollout_item(payload: dict, event_type: str = "response_item") -> dict:
    return {
        "timestamp": dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "type": event_type,
        "payload": payload,
    }


def session_meta_item(session_id: str, parent_thread_id: str | None = None) -> dict:
    payload = {"id": session_id}
    if parent_thread_id is not None:
        payload["parent_thread_id"] = parent_thread_id
        payload["agent_nickname"] = "test-subagent"
    return rollout_item(payload, event_type="session_meta")


def old_rollout_item(payload: dict, event_type: str = "response_item") -> dict:
    old = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=30)
    return {
        "timestamp": old.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "type": event_type,
        "payload": payload,
    }


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_rollout_running_to_done(tmp: Path) -> None:
    sessions = tmp / "sessions"
    rollout = sessions / "2026" / "06" / "07" / "rollout-test.jsonl"
    watcher = CodexRolloutStatus(sessions)
    write_line(rollout, rollout_item({"type": "reasoning"}))
    assert_equal(watcher.refresh()["status"], "green", "reasoning should be green")
    write_line(rollout, rollout_item({"type": "message", "role": "assistant", "phase": "final"}))
    assert_equal(watcher.refresh()["status"], "red", "final assistant message should be red")


def test_task_started_is_immediately_active(tmp: Path) -> None:
    sessions = tmp / "sessions"
    rollout = sessions / "2026" / "06" / "07" / "rollout-task-started.jsonl"
    watcher = CodexRolloutStatus(sessions)
    write_line(rollout, rollout_item({"type": "task_started"}, event_type="event_msg"))
    assert_equal(watcher.refresh()["status"], "green", "task_started should be active")
    write_line(rollout, rollout_item({"type": "task_complete"}, event_type="event_msg"))
    assert_equal(watcher.refresh()["status"], "red", "task_complete should return to idle")


def test_rollout_multi_session(tmp: Path) -> None:
    sessions = tmp / "sessions"
    first = sessions / "2026" / "06" / "07" / "rollout-first.jsonl"
    second = sessions / "2026" / "06" / "07" / "rollout-second.jsonl"
    watcher = CodexRolloutStatus(sessions)
    write_line(first, rollout_item({"type": "reasoning"}))
    write_line(second, rollout_item({"type": "reasoning"}))
    assert_equal(watcher.refresh()["status"], "green", "two running sessions should be green")
    write_line(first, rollout_item({"type": "message", "role": "assistant", "phase": "final"}))
    assert_equal(watcher.refresh()["status"], "green", "one remaining running session should stay green")
    write_line(second, rollout_item({"type": "message", "role": "assistant", "phase": "final"}))
    assert_equal(watcher.refresh()["status"], "red", "all sessions final should be red")


def test_subagent_completion_does_not_reduce_top_level_count(tmp: Path) -> None:
    sessions = tmp / "sessions"
    parent = sessions / "2026" / "06" / "07" / "rollout-parent.jsonl"
    child = sessions / "2026" / "06" / "07" / "rollout-child.jsonl"
    watcher = CodexRolloutStatus(sessions)
    write_line(parent, session_meta_item("parent-id"))
    write_line(parent, rollout_item({"type": "reasoning"}))
    write_line(child, session_meta_item("child-id", parent_thread_id="parent-id"))
    write_line(child, rollout_item({"type": "reasoning"}))
    snapshot = watcher.refresh()
    assert_equal(snapshot["status"], "green", "parent and child should be active")
    assert_equal(snapshot["active_count"], 1, "child should not be a separate top-level count")
    assert_equal(snapshot["raw_active_count"], 2, "diagnostics should retain raw active count")
    assert_equal(snapshot["subagent_active_count"], 1, "diagnostics should identify the active child")

    write_line(child, rollout_item({"type": "task_complete"}, event_type="event_msg"))
    snapshot = watcher.refresh()
    assert_equal(snapshot["status"], "green", "parent should remain active after child completion")
    assert_equal(snapshot["active_count"], 1, "child completion should not reduce top-level count")
    assert_equal(snapshot["subagent_active_count"], 0, "completed child should leave active sources")

    write_line(parent, rollout_item({"type": "task_complete"}, event_type="event_msg"))
    assert_equal(watcher.refresh()["status"], "red", "parent completion should still clear activity")


def test_rollout_old_active_times_out(tmp: Path) -> None:
    sessions = tmp / "sessions"
    rollout = sessions / "2026" / "06" / "07" / "rollout-old.jsonl"
    watcher = CodexRolloutStatus(sessions)
    write_line(rollout, old_rollout_item({"type": "reasoning"}))
    assert_equal(watcher.refresh()["status"], "red", "old active event should time out")


def test_rollout_task_complete_clears_green(tmp: Path) -> None:
    sessions = tmp / "sessions"
    rollout = sessions / "2026" / "06" / "07" / "rollout-task-complete.jsonl"
    watcher = CodexRolloutStatus(sessions)
    write_line(rollout, rollout_item({"type": "reasoning"}))
    assert_equal(watcher.refresh()["status"], "green", "reasoning should be green before task complete")
    write_line(rollout, rollout_item({"type": "task_complete"}, event_type="event_msg"))
    assert_equal(watcher.refresh()["status"], "red", "task_complete should clear green")


def test_tool_completed_status_does_not_clear_green(tmp: Path) -> None:
    sessions = tmp / "sessions"
    rollout = sessions / "2026" / "06" / "07" / "rollout-tool-completed.jsonl"
    watcher = CodexRolloutStatus(sessions)
    write_line(rollout, rollout_item({"type": "reasoning"}))
    assert_equal(watcher.refresh()["status"], "green", "reasoning should be green before tool completion")
    write_line(
        rollout,
        rollout_item(
            {"type": "patch_apply_end", "status": "completed"},
            event_type="event_msg",
        ),
    )
    assert_equal(
        watcher.refresh()["status"],
        "green",
        "tool-level completed status should not clear active turn",
    )
    write_line(rollout, rollout_item({"type": "task_complete"}, event_type="event_msg"))
    assert_equal(watcher.refresh()["status"], "red", "task complete should clear after tool completion")


def test_custom_tool_events_are_active(tmp: Path) -> None:
    sessions = tmp / "sessions"
    rollout = sessions / "2026" / "06" / "07" / "rollout-custom-tool.jsonl"
    watcher = CodexRolloutStatus(sessions)
    write_line(rollout, rollout_item({"type": "custom_tool_call"}))
    assert_equal(watcher.refresh()["status"], "green", "custom tool call should be active")
    write_line(rollout, rollout_item({"type": "custom_tool_call_output"}))
    assert_equal(watcher.refresh()["status"], "green", "custom tool output should remain active")
    write_line(rollout, rollout_item({"type": "task_complete"}, event_type="event_msg"))
    assert_equal(watcher.refresh()["status"], "red", "task complete should clear custom tool activity")


def test_rollout_manual_stop_clears_green(tmp: Path) -> None:
    sessions = tmp / "sessions"
    rollout = sessions / "2026" / "06" / "07" / "rollout-manual-stop.jsonl"
    watcher = CodexRolloutStatus(sessions)
    write_line(rollout, rollout_item({"type": "reasoning"}))
    assert_equal(watcher.refresh()["status"], "green", "reasoning should be green before manual stop")
    write_line(rollout, rollout_item({"type": "turn_aborted"}, event_type="event_msg"))
    assert_equal(watcher.refresh()["status"], "red", "turn_aborted should clear green")


def test_rollout_cancel_status_clears_green(tmp: Path) -> None:
    sessions = tmp / "sessions"
    rollout = sessions / "2026" / "06" / "07" / "rollout-cancel-status.jsonl"
    watcher = CodexRolloutStatus(sessions)
    write_line(rollout, rollout_item({"type": "function_call"}))
    assert_equal(watcher.refresh()["status"], "green", "tool call should be green before cancel")
    write_line(rollout, rollout_item({"type": "turn_state", "status": "cancelled"}, event_type="event_msg"))
    assert_equal(watcher.refresh()["status"], "red", "cancelled status should clear green")


def test_rollout_final_event_msg_clears_green(tmp: Path) -> None:
    sessions = tmp / "sessions"
    rollout = sessions / "2026" / "06" / "07" / "rollout-final-event-msg.jsonl"
    watcher = CodexRolloutStatus(sessions)
    write_line(rollout, rollout_item({"type": "agent_message"}, event_type="event_msg"))
    assert_equal(watcher.refresh()["status"], "green", "agent message should be green before final phase")
    write_line(rollout, rollout_item({"type": "agent_message", "phase": "final"}, event_type="event_msg"))
    assert_equal(watcher.refresh()["status"], "red", "final event_msg should clear green")


def test_ignored_event_does_not_refresh_stale_green(tmp: Path) -> None:
    sessions = tmp / "sessions"
    rollout = sessions / "2026" / "06" / "07" / "rollout-ignored-refresh.jsonl"
    watcher = CodexRolloutStatus(sessions)
    write_line(rollout, old_rollout_item({"type": "reasoning"}))
    write_line(rollout, rollout_item({"type": "unrelated_noise"}, event_type="event_msg"))
    assert_equal(watcher.refresh()["status"], "red", "ignored fresh event should not refresh stale green")


def test_token_count_is_not_active(tmp: Path) -> None:
    sessions = tmp / "sessions"
    rollout = sessions / "2026" / "06" / "07" / "rollout-token-count.jsonl"
    watcher = CodexRolloutStatus(sessions)
    write_line(rollout, rollout_item({"type": "token_count"}, event_type="event_msg"))
    assert_equal(watcher.refresh()["status"], "red", "token_count should not turn the light green")


def test_hook_yellow_priority() -> None:
    state = update_state("PermissionRequest", {"session_id": "test-hook"}, None)
    assert_equal(state["status"], "yellow", "permission request should be yellow")
    state = update_state("Stop", {"session_id": "test-hook"}, None)
    assert_equal(state["status"], "red", "stop should clear test hook session")


class StabilityProbe(TrafficLightIndicator):
    def __init__(self) -> None:
        self.current_status = "red"
        self.current_activity_status = "green"
        self.status_since = time.monotonic()
        self.completion_flash_started = None
        self.completion_flash_reason = "test"
        self.last_rollout_active_count = None


def test_green_hold() -> None:
    probe = StabilityProbe()
    held = probe.apply_stability({"status": "red", "source": "test", "reason": "immediate-red"})
    assert_equal(held["status"], "green", "green should be held briefly")


def test_hook_only_overrides_rollout_for_fresh_yellow() -> None:
    probe = StabilityProbe()
    rollout_active = {"status": "green", "source": "rollout"}
    rollout_idle = {"status": "red", "source": "rollout"}
    hook_running = {"status": "green", "source": "hook", "age_seconds": 1}
    hook_idle = {"status": "red", "source": "hook", "age_seconds": 1}
    hook_fresh_yellow = {"status": "yellow", "source": "hook", "age_seconds": 1}
    hook_stale_yellow = {
        "status": "yellow",
        "source": "hook",
        "age_seconds": HOOK_YELLOW_MAX_AGE_SECONDS + 1,
    }
    assert_equal(
        probe.choose_status(hook_running, rollout_idle)["source"],
        "rollout",
        "hook green should not decide idle/running",
    )
    assert_equal(
        probe.choose_status(hook_idle, rollout_active)["source"],
        "rollout",
        "hook red should not decide idle/running",
    )
    assert_equal(
        probe.choose_status(hook_fresh_yellow, rollout_active)["status"],
        "yellow",
        "fresh hook yellow should override rollout",
    )
    assert_equal(
        probe.choose_status(hook_stale_yellow, rollout_active)["source"],
        "rollout",
        "stale hook yellow should not override rollout",
    )


def test_display_colors_are_inverted() -> None:
    assert_equal(DISPLAY_STATUS["green"], "red", "active should display red")
    assert_equal(DISPLAY_STATUS["red"], "green", "idle should display green")
    assert_equal(DISPLAY_STATUS["yellow"], "yellow", "waiting should display yellow")


def test_completion_flash_runs_for_three_seconds() -> None:
    probe = StabilityProbe()
    now = time.monotonic()
    probe.current_status = "green"
    probe.completion_flash_started = now
    half_period = COMPLETION_BLINK_HALF_PERIOD_SECONDS
    samples = []
    for phase in range(COMPLETION_BLINK_COUNT * 2):
        probe.completion_flash_started = time.monotonic() - (phase * half_period + 0.01)
        samples.append(probe.completion_flash_intensity())
    assert_equal(samples, [1.0, 0.12, 1.0, 0.12, 1.0, 0.12], "completion blink phases")
    probe.completion_flash_started = time.monotonic() - (COMPLETION_FLASH_SECONDS + 0.01)
    assert_equal(probe.completion_flash_intensity(), 1.0, "completion should settle after flash")


def test_partial_completion_flash_returns_to_running_red() -> None:
    probe = StabilityProbe()
    now = time.monotonic()
    probe.last_rollout_active_count = 3
    probe.update_completion_flash("green", {"active_count": 2}, now)
    assert_equal(
        probe.display_status_for("green", now + 0.1),
        "green",
        "active count drop should show green flash",
    )
    assert_equal(
        probe.display_status_for("green", now + COMPLETION_FLASH_SECONDS + 0.1),
        "red",
        "remaining active tasks should return to running red after green flash",
    )


def test_final_completion_flash_settles_on_idle_green() -> None:
    probe = StabilityProbe()
    now = time.monotonic()
    probe.last_rollout_active_count = 1
    probe.update_completion_flash("red", {"active_count": 0}, now)
    assert_equal(
        probe.display_status_for("red", now + 0.1),
        "green",
        "final active count drop should show green flash",
    )
    assert_equal(
        probe.display_status_for("red", now + COMPLETION_FLASH_SECONDS + 0.1),
        "green",
        "idle status should remain green after final flash",
    )


def test_yellow_suppresses_completion_flash() -> None:
    probe = StabilityProbe()
    now = time.monotonic()
    probe.last_rollout_active_count = 2
    probe.update_completion_flash("yellow", {"active_count": 1}, now)
    assert_equal(
        probe.display_status_for("yellow", now + 0.1),
        "yellow",
        "yellow should not be hidden by green flash",
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="traffic-light-tests-") as tmp_dir:
        tmp = Path(tmp_dir)
        test_rollout_running_to_done(tmp)
        test_task_started_is_immediately_active(tmp)
        test_rollout_multi_session(tmp)
        test_subagent_completion_does_not_reduce_top_level_count(tmp)
        test_rollout_old_active_times_out(tmp)
        test_rollout_task_complete_clears_green(tmp)
        test_tool_completed_status_does_not_clear_green(tmp)
        test_custom_tool_events_are_active(tmp)
        test_rollout_manual_stop_clears_green(tmp)
        test_rollout_cancel_status_clears_green(tmp)
        test_rollout_final_event_msg_clears_green(tmp)
        test_ignored_event_does_not_refresh_stale_green(tmp)
        test_token_count_is_not_active(tmp)
    test_hook_yellow_priority()
    test_green_hold()
    test_hook_only_overrides_rollout_for_fresh_yellow()
    test_display_colors_are_inverted()
    test_completion_flash_runs_for_three_seconds()
    test_partial_completion_flash_returns_to_running_red()
    test_final_completion_flash_settles_on_idle_green()
    test_yellow_suppresses_completion_flash()
    print("status source tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
