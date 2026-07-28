#!/usr/bin/env python3
"""Capture visible Windows top-level windows that belong to Codex."""

from __future__ import annotations

import argparse
import ctypes
import json
from ctypes import wintypes
from pathlib import Path
from typing import Any


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_PATH_CHARS = 32768

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL


def get_window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def get_window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def get_process_path(pid: int) -> str | None:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(MAX_PATH_CHARS)
        buffer = ctypes.create_unicode_buffer(MAX_PATH_CHARS)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


def get_window_rect(hwnd: int) -> dict[str, int] | None:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return {
        "left": int(rect.left),
        "top": int(rect.top),
        "right": int(rect.right),
        "bottom": int(rect.bottom),
        "width": int(rect.right - rect.left),
        "height": int(rect.bottom - rect.top),
    }


def is_codex_process(path: str | None, title: str) -> bool:
    if not path:
        return "codex" in title.lower()
    lower_path = path.lower()
    name = Path(path).name.lower()
    if name.startswith("codex"):
        return True
    if name == "chatgpt.exe" and "openai.codex_" in lower_path:
        return True
    if "\\openai\\codex\\" in lower_path:
        return True
    if "openai.codex_" in lower_path:
        return True
    return "codex" in title.lower()


def enumerate_codex_windows() -> dict[str, Any]:
    foreground = int(user32.GetForegroundWindow() or 0)
    windows: list[dict[str, Any]] = []
    callback_errors: list[str] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            title = get_window_text(hwnd)
            pid = get_window_pid(hwnd)
            path = get_process_path(pid)
            if not is_codex_process(path, title):
                return True
            rect = get_window_rect(hwnd)
            hwnd_value = int(hwnd) if isinstance(hwnd, int) else int(hwnd.value)
            windows.append(
                {
                    "hwnd": hwnd_value,
                    "pid": pid,
                    "process_name": Path(path).name if path else None,
                    "process_path": path,
                    "title": title,
                    "is_minimized": bool(user32.IsIconic(hwnd)),
                    "is_foreground": hwnd_value == foreground,
                    "rect": rect,
                }
            )
        except Exception as exc:
            if len(callback_errors) < 10:
                callback_errors.append(str(exc))
            return True
        return True

    callback_ref = EnumWindowsProc(callback)
    ctypes.set_last_error(0)
    if not user32.EnumWindows(callback_ref, 0):
        error = ctypes.get_last_error()
        return {
            "source": "win32",
            "window_count": 0,
            "windows": [],
            "error": f"EnumWindows failed: {error}",
        }

    windows.sort(key=lambda item: (item.get("is_minimized", False), str(item.get("title") or ""), item["pid"]))
    return {
        "source": "win32",
        "window_count": len(windows),
        "visible_count": sum(1 for item in windows if not item.get("is_minimized")),
        "foreground_count": sum(1 for item in windows if item.get("is_foreground")),
        "windows": windows,
        "error": "; ".join(callback_errors) if callback_errors else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe real Windows top-level Codex windows.")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    print(json.dumps(enumerate_codex_windows(), ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
