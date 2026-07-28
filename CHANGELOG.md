# Change Log

## 2026-07-28

- Changed completion feedback from a final-only blink to a 3-second green flash on any rollout active-count drop, including `3 -> 2`, `2 -> 1`, and `1 -> 0`.
- After a partial completion flash, the indicator returns to running red when other conversations remain active.
- Removed the running red pulse and yellow pulse; red and yellow are now steady.
- Reverted the Pillow renderer to final-size opaque drawing to avoid color-key edge fringes and restored the previous body corner radius.
- Added Windows DPI-aware native rendering: the logical 72x106 design is drawn directly at the monitor's physical DPI without resizing back down.
- Aligned the lamp group to the body center and removed the previous 3px downward coordinate bias.
- Excluded child-agent rollouts from the completion count so a child-agent finish does not trigger a green flash; retained child activity as running evidence.
- Added regression coverage for partial completion flash, final completion flash, and yellow overriding completion flash.
- Backed up the previous implementation under `backups\before-partial-green-flash-modern-ui-20260728-182546`.
- Backed up this pre-revert implementation under `backups\before-visual-revert-no-pulse-20260728-183156`.
- Backed up this pre-DPI implementation under `backups\before-native-dpi-render-183707`.
- Backed up this pre-alignment implementation under `backups\before-lamp-alignment-184031`.
- Backed up this pre-subagent-count implementation under `backups\before-ignore-subagent-completion-184634`.

## 2026-06-11

- Inverted the display meaning: red now means at least one Codex turn is running, while green means all turns are complete.
- Added `event_msg: task_started` as an immediate active signal so the lamp changes as soon as Codex starts thinking.
- Added a three-cycle, medium-speed green completion blink when the final active or waiting turn becomes idle.
- Kept yellow as the waiting-for-user state.
- Added regression coverage for task start detection, inverted display colors, and completion blink timing.
- Backed up the previous implementation under `backups\before-invert-and-completion-blink-20260611-160542`.

## 2026-07-16

- Changed status arbitration so rollout decides red/green and hooks only override with a fresh yellow waiting-for-approval state.
- Added a 30-minute freshness limit for hook yellow to avoid stale hook state keeping the lamp in the wrong mode.
- Treated hook state read errors as non-authoritative instead of forcing yellow.
- Added regression coverage for hook-vs-rollout arbitration.
- Backed up the previous implementation under `backups\before-hook-yellow-only-20260716-144404`.
- Fixed false completion blinks caused by tool-level `status: completed` events such as `patch_apply_end`.
- Added `custom_tool_call` and `custom_tool_call_output` as active rollout evidence.
- Added regression coverage for tool-level completion not clearing a running turn.
- Backed up the previous implementation under `backups\before-tool-status-completed-fix-20260716-150319`.
- Added persistent indicator observation logs:
  - `runtime\transitions.jsonl` records every displayed lamp transition.
  - `runtime\observations.jsonl` records startup, transitions, active-source changes, and 30-second heartbeats.
- Added `codex_window_status.py` and attached a Win32 Codex top-level-window snapshot to diagnostics and observation logs.
- Added `restart-indicator.ps1` and `restart-indicator.bat` to reload the floating indicator after code changes without killing unrelated Python processes.
- Backed up the previous implementation under `backups\before-transition-logging-20260716-145008`.
- Backed up the previous implementation under `backups\before-window-status-logging-20260716-145444`.

## 2026-06-05

- Created a portable Windows traffic-light indicator under this folder.
- Added `indicator.py`, a small always-on-top Tkinter floating window.
- Added `codex_status_hook.py`, a short Codex hook target that writes status to `runtime/state.json`.
- Added `install-user-hooks.ps1` and `uninstall-user-hooks.ps1`; both back up `~/.codex/hooks.json` before changing it.
- Added `hooks.example.json` as a readable example of the hook shape.
- Added `start-indicator.bat` for double-click startup.
- Hook definitions include both `command` and `commandWindows` so they match the documented base command shape while still being explicit on Windows.
- Changed `start-indicator.bat` to launch `indicator.py` through `pythonw.exe`, so the console window does not remain open.
- Added `start-indicator-hidden.vbs` for no-console startup.
- Added `start-indicator-debug.bat` to preserve the old visible-console behavior for troubleshooting.
- Removed semi-transparent drop shadow and alpha antialiasing from the Tkinter indicator renderer to avoid black speckled edges on Windows transparent-color windows.
- Added `codex_log_status.py` and connected it to `indicator.py` as a red/green fallback source when Codex hooks are not yet trusted, reloaded, or firing.
- Kept yellow status hook-driven because approval/waiting inference from logs is too noisy.
- Added `codex_rollout_status.py` and switched `indicator.py` from SQLite log polling to rollout JSONL polling for the red/green fallback source.
- Added a 1.5 second green hold stabilizer to avoid flicker during short thinking/tool transitions.
- Added `runtime/diagnostics.json` output plus a right-click `Open diagnostics` menu item.
- Updated hook mapping to include `SessionStart -> red` and `PostToolUse -> green`.
- Added `test_status_sources.py` regression checks for rollout state, hook yellow, multi-session aggregation, and green hold behavior.
- Fixed rollout watcher completion handling for `event_msg: task_complete`, so completed rollout files clear green state.
- Prevented ignored/noise events from refreshing stale green state; this avoids residual green lights after a task has ended.
- Added active rollout source details to diagnostics for easier debugging when the light stays green.
- Added `diagnose-status.bat` for a double-click status probe that shows rollout, hook state, and diagnostics in one paused console window.
- Removed `event_msg: token_count` from rollout active events; token-count records are turn accounting, not evidence that Codex is still running.

No global Codex configuration is changed by these files until `install-user-hooks.ps1` is run.
