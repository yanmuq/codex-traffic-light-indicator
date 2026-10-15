#!/usr/bin/env python3
"""Small always-on-top traffic-light window for Codex status."""

from __future__ import annotations

import json
import ctypes
import os
import tempfile
import time
import datetime as dt
from pathlib import Path

# Keep Tcl/Tk discovery deterministic for the portable runtime used on this
# machine. These variables must exist before Tk creates its first interpreter.
if os.name == "nt":
    _local_python_runtime = Path(__file__).resolve().parent / "python-runtime-release"
    _system_python_runtime = Path("C:/Python313")
    _tcl_library = os.environ.get("CODEX_TRAFFIC_LIGHT_TCL_LIBRARY")
    _tk_library = os.environ.get("CODEX_TRAFFIC_LIGHT_TK_LIBRARY")
    if not _tcl_library and (_system_python_runtime / "tcl" / "tcl8.6").is_dir():
        _tcl_library = str(_system_python_runtime / "tcl" / "tcl8.6")
        _tk_library = str(_system_python_runtime / "tcl" / "tk8.6")
    _tcl_library = _tcl_library or str(_local_python_runtime / "tcl" / "tcl8.6")
    _tk_library = _tk_library or str(_local_python_runtime / "tcl" / "tk8.6")
    if Path(_tcl_library).is_dir():
        os.environ.setdefault("TCL_LIBRARY", _tcl_library)
    if Path(_tk_library).is_dir():
        os.environ.setdefault("TK_LIBRARY", _tk_library)

import tkinter as tk
from tkinter import messagebox

from codex_window_status import enumerate_codex_windows
from codex_rollout_status import CodexRolloutStatus, status_priority

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:  # pragma: no cover - fallback path for minimal Python installs.
    Image = ImageDraw = ImageTk = None


APP_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = APP_DIR / "runtime"
STATE_PATH = RUNTIME_DIR / "state.json"
DIAGNOSTICS_PATH = RUNTIME_DIR / "diagnostics.json"
TRANSITIONS_PATH = RUNTIME_DIR / "transitions.jsonl"
OBSERVATIONS_PATH = RUNTIME_DIR / "observations.jsonl"

WINDOW_W = 72
WINDOW_H = 106
POLL_MS = 300
ACTIVE_MIN_SECONDS = 1.5
COMPLETION_BLINK_COUNT = 3
COMPLETION_BLINK_HALF_PERIOD_SECONDS = 0.4
COMPLETION_FLASH_SECONDS = 3.0
HOOK_YELLOW_MAX_AGE_SECONDS = 30 * 60
OBSERVATION_HEARTBEAT_SECONDS = 30
WINDOW_SNAPSHOT_INTERVAL_SECONDS = 3
LOG_MAX_BYTES = 25 * 1024 * 1024
TRANSPARENT = "#020203"
BASE_DPI = 96.0
TOPMOST_REFRESH_MS = 1000

DISPLAY_STATUS = {
    "red": "green",
    "green": "red",
    "yellow": "yellow",
}

COLORS = {
    "red": (255, 87, 78),
    "yellow": (255, 204, 84),
    "green": (48, 209, 88),
    "off": (43, 47, 55),
    "body": (28, 31, 37),
    "body_edge": (78, 84, 96),
    "body_highlight": (52, 57, 66),
}


def enable_windows_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        # Render at the monitor's physical DPI so Windows does not bitmap-scale
        # the small 72x106 source image after the fact.
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


def enforce_windows_topmost(window_id: int) -> None:
    """Move the Tk top-level wrapper to the front without taking focus."""
    if os.name != "nt":
        return
    try:
        user32 = ctypes.windll.user32
        get_ancestor = user32.GetAncestor
        get_ancestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        get_ancestor.restype = ctypes.c_void_p
        set_window_pos = user32.SetWindowPos
        set_window_pos.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        set_window_pos.restype = ctypes.c_int

        # Tk exposes a child HWND through winfo_id(); GA_ROOT resolves the real
        # top-level wrapper that participates in the desktop Z order.
        hwnd = get_ancestor(ctypes.c_void_p(window_id), 2) or window_id
        flags = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
        set_window_pos(
            ctypes.c_void_p(hwnd),
            ctypes.c_void_p(-1),  # HWND_TOPMOST
            0,
            0,
            0,
            0,
            flags,
        )
    except (AttributeError, OSError, TypeError, ValueError):
        pass


class TrafficLightIndicator:
    def __init__(self) -> None:
        enable_windows_dpi_awareness()
        self.root = tk.Tk()
        self.root.title("Codex Traffic Light")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        self.root.configure(bg=TRANSPARENT)
        self.render_scale = max(1.0, self.root.winfo_fpixels("1i") / BASE_DPI)
        self.pixel_w = max(1, round(WINDOW_W * self.render_scale))
        self.pixel_h = max(1, round(WINDOW_H * self.render_scale))
        self.root.geometry(
            f"{self.pixel_w}x{self.pixel_h}+{round(120 * self.render_scale)}+{round(120 * self.render_scale)}"
        )

        self.canvas = tk.Canvas(
            self.root,
            width=self.pixel_w,
            height=self.pixel_h,
            highlightthickness=0,
            bd=0,
            bg=TRANSPARENT,
        )
        self.canvas.pack(fill="both", expand=True)

        self.drag_start: tuple[int, int] | None = None
        self.current_status = "green"
        self.current_activity_status = "red"
        self.current_source = "initial"
        self.last_state_mtime = 0.0
        self.last_hook_snapshot: dict[str, object] = {"status": "red", "source": "hook", "reason": "initial"}
        self.rollout_status = CodexRolloutStatus()
        self.latest_hook_snapshot: dict[str, object] = self.last_hook_snapshot
        self.latest_rollout_snapshot: dict[str, object] = self.rollout_status.last_snapshot
        self.status_since = time.monotonic()
        self.completion_flash_started: float | None = None
        self.completion_flash_reason = "initial"
        self.last_rollout_active_count: int | None = None
        self.last_window_snapshot: dict[str, object] = {
            "source": "win32",
            "window_count": 0,
            "visible_count": 0,
            "foreground_count": 0,
            "windows": [],
            "error": "not-yet-sampled",
        }
        self.last_window_snapshot_at = 0.0
        self.last_observation_fingerprint: str | None = None
        self.last_observation_log_at = 0.0
        self.tick = 0
        self.photo = None

        self.canvas.bind("<ButtonPress-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.finish_drag)
        self.canvas.bind("<Button-3>", self.show_menu)
        self.root.bind("<Map>", lambda _event: self.ensure_topmost(), add="+")
        self.root.bind("<Escape>", lambda _event: self.root.destroy())

        self.menu = tk.Menu(self.root, tearoff=False)
        self.menu.add_command(label="Open diagnostics", command=self.open_diagnostics)
        self.menu.add_command(label="Open runtime folder", command=self.open_runtime_folder)
        self.menu.add_command(label="Exit", command=self.root.destroy)

        self.ensure_initial_state()
        self.log_indicator_start()
        self.refresh()
        self.root.after_idle(self.maintain_topmost)

    def ensure_initial_state(self) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        if not STATE_PATH.exists():
            STATE_PATH.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "status": "red",
                        "updated_at": None,
                        "reason": "indicator-start",
                        "session_count": 0,
                        "sessions": {},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

    def start_drag(self, event: tk.Event) -> None:
        self.drag_start = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def drag(self, event: tk.Event) -> None:
        if self.drag_start is None:
            return
        dx, dy = self.drag_start
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def finish_drag(self, _event: tk.Event) -> None:
        self.drag_start = None
        self.ensure_topmost()

    def show_menu(self, event: tk.Event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self.menu.grab_release()
            except tk.TclError:
                pass
            self.ensure_topmost()

    def ensure_topmost(self) -> None:
        try:
            self.root.attributes("-topmost", True)
            enforce_windows_topmost(self.root.winfo_id())
        except tk.TclError:
            pass

    def maintain_topmost(self) -> None:
        self.ensure_topmost()
        try:
            self.root.after(TOPMOST_REFRESH_MS, self.maintain_topmost)
        except tk.TclError:
            pass

    def open_runtime_folder(self) -> None:
        import os

        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(RUNTIME_DIR)  # type: ignore[attr-defined]

    def open_diagnostics(self) -> None:
        import os

        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        if not DIAGNOSTICS_PATH.exists():
            self.atomic_write_json(
                DIAGNOSTICS_PATH,
                {"current_status": self.current_status, "current_source": self.current_source},
            )
        os.startfile(DIAGNOSTICS_PATH)  # type: ignore[attr-defined]

    def atomic_write_json(self, path: Path, data: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
        with open(fd, "w", encoding="utf-8", closefd=True) as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        Path(tmp_name).replace(path)

    def now_iso(self) -> str:
        return dt.datetime.now().astimezone().isoformat(timespec="milliseconds")

    def append_jsonl(self, path: Path, item: dict[str, object]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
                archive = path.with_suffix(path.suffix + ".old")
                try:
                    archive.unlink(missing_ok=True)
                except OSError:
                    pass
                path.replace(archive)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            pass

    def compact_snapshot(self, snapshot: dict[str, object]) -> dict[str, object]:
        compact: dict[str, object] = {
            "status": snapshot.get("status"),
            "source": snapshot.get("source"),
            "reason": snapshot.get("reason"),
        }
        for key in (
            "active_count",
            "source_path",
            "source_event",
            "source_payload",
            "watched_count",
            "sessions_root",
            "error",
            "age_seconds",
            "session_count",
        ):
            if key in snapshot:
                compact[key] = snapshot.get(key)
        active_sources = snapshot.get("active_sources")
        if isinstance(active_sources, list):
            compact["active_sources"] = active_sources
        return compact

    def observation_fingerprint(
        self,
        snapshot: dict[str, object],
        hook_snapshot: dict[str, object],
        rollout_snapshot: dict[str, object],
        window_snapshot: dict[str, object],
        activity_status: str,
        display_status: str,
    ) -> str:
        return json.dumps(
            {
                "activity_status": activity_status,
                "display_status": display_status,
                "chosen": self.compact_snapshot(snapshot),
                "hook": self.compact_snapshot(hook_snapshot),
                "rollout": self.compact_snapshot(rollout_snapshot),
                "windows": window_snapshot,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    def log_indicator_start(self) -> None:
        self.append_jsonl(
            OBSERVATIONS_PATH,
            {
                "event": "indicator_start",
                "timestamp": self.now_iso(),
                "pid": os.getpid(),
                "poll_ms": POLL_MS,
                "active_min_seconds": ACTIVE_MIN_SECONDS,
                "heartbeat_seconds": OBSERVATION_HEARTBEAT_SECONDS,
                "window_snapshot_interval_seconds": WINDOW_SNAPSHOT_INTERVAL_SECONDS,
                "completion_flash_seconds": COMPLETION_FLASH_SECONDS,
            },
        )

    def read_window_snapshot(self) -> dict[str, object]:
        now = time.monotonic()
        if now - self.last_window_snapshot_at < WINDOW_SNAPSHOT_INTERVAL_SECONDS:
            return self.last_window_snapshot
        try:
            self.last_window_snapshot = enumerate_codex_windows()
        except Exception as exc:
            self.last_window_snapshot = {
                "source": "win32",
                "window_count": 0,
                "visible_count": 0,
                "foreground_count": 0,
                "windows": [],
                "error": str(exc),
            }
        self.last_window_snapshot_at = now
        return self.last_window_snapshot

    def log_status_observation(
        self,
        previous_activity_status: str,
        previous_display_status: str,
        snapshot: dict[str, object],
        hook_snapshot: dict[str, object],
        rollout_snapshot: dict[str, object],
        window_snapshot: dict[str, object],
        activity_status: str,
        display_status: str,
    ) -> None:
        now = time.monotonic()
        fingerprint = self.observation_fingerprint(
            snapshot,
            hook_snapshot,
            rollout_snapshot,
            window_snapshot,
            activity_status,
            display_status,
        )
        status_changed = (
            previous_activity_status != activity_status
            or previous_display_status != display_status
        )
        source_changed = fingerprint != self.last_observation_fingerprint
        heartbeat_due = now - self.last_observation_log_at >= OBSERVATION_HEARTBEAT_SECONDS
        if not (status_changed or source_changed or heartbeat_due):
            return

        event = "transition" if status_changed else "source_change" if source_changed else "heartbeat"
        entry = {
            "event": event,
            "timestamp": self.now_iso(),
            "activity_status": activity_status,
            "display_status": display_status,
            "previous_activity_status": previous_activity_status,
            "previous_display_status": previous_display_status,
            "chosen": self.compact_snapshot(snapshot),
            "hook": self.compact_snapshot(hook_snapshot),
            "rollout": self.compact_snapshot(rollout_snapshot),
            "windows": window_snapshot,
        }
        self.append_jsonl(OBSERVATIONS_PATH, entry)
        if status_changed:
            self.append_jsonl(TRANSITIONS_PATH, entry)
        self.last_observation_fingerprint = fingerprint
        self.last_observation_log_at = now

    def read_hook_snapshot(self) -> dict[str, object]:
        try:
            mtime = STATE_PATH.stat().st_mtime
            if mtime == self.last_state_mtime:
                return self.last_hook_snapshot
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            self.last_state_mtime = mtime
            status = data.get("status", "red")
            if status in {"red", "yellow", "green"}:
                updated_at = data.get("updated_at")
                sessions = data.get("sessions", {})
                self.last_hook_snapshot = {
                    "status": status,
                    "source": "hook",
                    "reason": data.get("reason", "state-file"),
                    "updated_at": updated_at,
                    "age_seconds": self.age_seconds(updated_at),
                    "session_count": data.get("session_count", 0),
                    "session_ids": (
                        [
                            session_id
                            for session_id, session in sessions.items()
                            if isinstance(session, dict)
                            and session.get("status") in {"running", "waiting"}
                        ]
                        if isinstance(sessions, dict) else []
                    ),
                }
                return self.last_hook_snapshot
        except Exception:
            return {"status": "red", "source": "hook", "reason": "state-file-read-error"}
        return {"status": "red", "source": "hook", "reason": "state-file-invalid"}

    def read_status_snapshot(self) -> dict[str, object]:
        hook_snapshot = self.read_hook_snapshot()
        rollout_snapshot = self.rollout_status.refresh(
            session_ids=hook_snapshot.get("session_ids", [])
        )
        self.latest_hook_snapshot = hook_snapshot
        self.latest_rollout_snapshot = rollout_snapshot
        chosen = self.choose_status(hook_snapshot, rollout_snapshot)
        stable = self.apply_stability(chosen)
        self.write_diagnostics(stable, hook_snapshot, rollout_snapshot)
        return stable

    def choose_status(
        self,
        hook_snapshot: dict[str, object],
        rollout_snapshot: dict[str, object],
    ) -> dict[str, object]:
        if self.is_fresh_hook_yellow(hook_snapshot):
            return hook_snapshot
        return rollout_snapshot

    def is_fresh_hook_yellow(self, hook_snapshot: dict[str, object]) -> bool:
        if hook_snapshot.get("status") != "yellow":
            return False
        age = hook_snapshot.get("age_seconds")
        if isinstance(age, (int, float)):
            return age <= HOOK_YELLOW_MAX_AGE_SECONDS
        return False

    def age_seconds(self, value: object) -> float | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            parsed = dt.datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.UTC)
            return max(0.0, (dt.datetime.now(dt.UTC) - parsed).total_seconds())
        except ValueError:
            return None

    def apply_stability(self, next_snapshot: dict[str, object]) -> dict[str, object]:
        current_time = time.monotonic()
        next_status = str(next_snapshot.get("status", "red"))
        if (
            self.current_activity_status == "green"
            and next_status == "red"
            and current_time - self.status_since < ACTIVE_MIN_SECONDS
        ):
            held = dict(next_snapshot)
            held["status"] = "green"
            held["source"] = "stabilizer"
            held["reason"] = "active-min-hold"
            return held
        if next_status != self.current_activity_status:
            self.status_since = current_time
        return next_snapshot

    def write_diagnostics(
        self,
        chosen: dict[str, object],
        hook_snapshot: dict[str, object],
        rollout_snapshot: dict[str, object],
    ) -> None:
        try:
            self.atomic_write_json(
                DIAGNOSTICS_PATH,
                {
                    "chosen": chosen,
                    "hook": hook_snapshot,
                    "rollout": rollout_snapshot,
                    "windows": self.read_window_snapshot(),
                    "current_activity_status": self.current_activity_status,
                    "current_display_status": self.current_status,
                    "completion_flash_active": self.completion_flash_started is not None,
                    "completion_flash_reason": self.completion_flash_reason,
                    "updated_at_epoch": time.time(),
                },
            )
        except OSError:
            pass

    def refresh(self) -> None:
        snapshot = self.read_status_snapshot()
        activity_status = str(snapshot.get("status", "red"))
        current_time = time.monotonic()
        self.update_completion_flash(activity_status, self.latest_rollout_snapshot, current_time)
        display_status = self.display_status_for(activity_status, current_time)
        window_snapshot = self.read_window_snapshot()
        previous_activity_status = self.current_activity_status
        previous_display_status = self.current_status
        self.current_activity_status = activity_status
        self.current_status = display_status
        self.current_source = str(snapshot.get("source", "unknown"))
        self.log_status_observation(
            previous_activity_status,
            previous_display_status,
            snapshot,
            self.latest_hook_snapshot,
            self.latest_rollout_snapshot,
            window_snapshot,
            activity_status,
            display_status,
        )
        self.draw(self.current_status)
        self.tick += 1
        self.root.after(POLL_MS, self.refresh)

    def update_completion_flash(
        self,
        activity_status: str,
        rollout_snapshot: dict[str, object],
        current_time: float,
    ) -> None:
        active_count_value = rollout_snapshot.get("active_count")
        active_count = active_count_value if isinstance(active_count_value, int) else 0
        previous_count = self.last_rollout_active_count
        self.last_rollout_active_count = active_count
        if activity_status == "yellow" or previous_count is None:
            return
        if previous_count > active_count:
            self.completion_flash_started = current_time
            self.completion_flash_reason = f"active-count-drop:{previous_count}->{active_count}"

    def display_status_for(self, activity_status: str, current_time: float) -> str:
        if activity_status == "yellow":
            self.completion_flash_started = None
            return "yellow"
        if self.completion_flash_started is not None:
            if current_time - self.completion_flash_started < COMPLETION_FLASH_SECONDS:
                return "green"
            self.completion_flash_started = None
        return DISPLAY_STATUS.get(activity_status, "green")

    def draw(self, status: str) -> None:
        if status == "green":
            blink = self.completion_flash_intensity()
        else:
            blink = 1.0
        if Image is not None and ImageDraw is not None and ImageTk is not None:
            self.draw_pillow(status, blink)
        else:
            self.draw_canvas(status, blink)

    def completion_flash_intensity(self) -> float:
        if self.completion_flash_started is None:
            return 1.0
        elapsed = time.monotonic() - self.completion_flash_started
        if elapsed >= COMPLETION_FLASH_SECONDS:
            self.completion_flash_started = None
            return 1.0
        phase = int(elapsed / COMPLETION_BLINK_HALF_PERIOD_SECONDS)
        return 1.0 if phase % 2 == 0 else 0.12

    def lamp_color(self, lamp: str, status: str, blink: float) -> tuple[int, int, int]:
        if lamp != status:
            return COLORS["off"]
        base = COLORS[lamp]
        if lamp in {"red", "yellow", "green"}:
            return tuple(int(channel * blink) for channel in base)
        return base

    def draw_pillow(self, status: str, blink: float) -> None:
        # Draw directly at the DPI-scaled window size. There is no downsampling
        # step, so the color-keyed transparent edge stays crisp.
        scale = self.render_scale
        image = Image.new("RGB", (self.pixel_w, self.pixel_h), TRANSPARENT)
        draw = ImageDraw.Draw(image)

        def px(value: float) -> int:
            return round(value * scale)

        def box(x1: float, y1: float, x2: float, y2: float) -> tuple[int, int, int, int]:
            return (px(x1), px(y1), px(x2), px(y2))

        draw.rounded_rectangle(box(15, 4, 56, 99), radius=px(13), fill=COLORS["body_edge"])
        draw.rounded_rectangle(box(17, 6, 54, 97), radius=px(11), fill=COLORS["body"])

        lamps = [("red", 27), ("yellow", 52), ("green", 77)]
        for lamp, cy in lamps:
            color = self.lamp_color(lamp, status, blink)
            draw.ellipse(
                box(22.5, cy - 13, 48.5, cy + 13),
                fill=(10, 11, 13),
                outline=(4, 5, 6),
                width=max(1, px(1)),
            )
            if lamp == status:
                softened = tuple(max(0, int(channel * 0.42)) for channel in color)
                draw.ellipse(box(19.5, cy - 16, 51.5, cy + 16), fill=softened)
            draw.ellipse(box(24.5, cy - 11, 46.5, cy + 11), fill=color)
            highlight = tuple(min(255, int(channel * 1.18)) for channel in color)
            if lamp == status:
                draw.ellipse(box(29.5, cy - 8, 37.5, cy), fill=highlight)
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")

    def draw_canvas(self, status: str, blink: float) -> None:
        self.canvas.delete("all")
        scale = self.render_scale

        def px(value: float) -> int:
            return round(value * scale)

        self.canvas.create_rectangle(px(16), px(5), px(56), px(99), fill="#3a3e46", outline="")
        self.canvas.create_rectangle(px(18), px(7), px(54), px(97), fill="#121418", outline="")
        for lamp, cy in [("red", 27), ("yellow", 52), ("green", 77)]:
            color = "#%02x%02x%02x" % self.lamp_color(lamp, status, blink)
            self.canvas.create_oval(
                px(22.5), px(cy - 13), px(48.5), px(cy + 13), fill="#0a0b0d", outline=""
            )
            self.canvas.create_oval(
                px(24.5), px(cy - 11), px(46.5), px(cy + 11), fill=color, outline=""
            )

    def run(self) -> None:
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.root.destroy()
        except Exception as exc:
            messagebox.showerror("Codex Traffic Light", str(exc))


def main() -> int:
    TrafficLightIndicator().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
