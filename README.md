# Codex 红绿灯便携指示器

这是一个便携版 Windows 红绿灯指示器，用一个始终置顶的小窗口显示 Codex 任务状态。它不 patch Codex App，不替换系统文件，也不依赖原生宠物的 hover/动画状态。窗口会按当前显示器 DPI 直接绘制，不把低分辨率图像放大后交给 Windows 缩放。

## 项目做什么

它把 Codex 的多个状态来源统一成三个可见信号：

- 红灯：至少有一个顶层对话/项目正在运行、思考、搜索或调用工具。
- 黄灯：至少有一个对话等待用户批准、输入或介入，优先级最高。
- 绿灯：顶层任务全部空闲或已完成。任一顶层任务完成时，绿灯闪烁 3 秒；如果其它顶层任务仍在运行，随后回到红灯。

子 agent 的运行会继续作为主对话的运行证据，但子 agent 完成不会单独触发绿灯提示。工具级的 `status: completed` 也不会被当成整轮任务完成。

## 完整工作链条

```text
Codex hooks / rollout JSONL / Win32 窗口快照
                 |
                 v
       状态源读取与事件分类
                 |
                 +--> hook: 只负责新鲜的等待授权黄灯
                 +--> rollout: 判断顶层任务运行/完成
                 +--> window: 记录真实窗口证据，不直接决定红绿
                 |
                 v
       父对话与子 agent 关系识别
                 |
                 +--> 所有 active rollout 保留为运行证据
                 +--> active_count 只统计顶层任务
                 +--> 子 agent 完成不减少顶层计数
                 |
                 v
             状态仲裁
                 |
                 +--> 新鲜黄灯覆盖其它颜色
                 +--> 运行状态映射为红灯
                 +--> 空闲状态映射为绿灯
                 |
                 v
       顶层 active_count 下降？
                 |
                 +--> 是：绿灯闪烁 3 秒
                 +--> 仍有顶层任务：回到红灯
                 +--> 没有顶层任务：保持绿灯
                 |
                 v
       DPI 直出渲染 + diagnostics/observations/transitions 日志
```

状态源的优先顺序不是简单的“谁最后写入谁负责”：rollout 负责运行/完成，hook 只覆盖新鲜的等待授权状态，窗口枚举只用于复盘桌面上实际存在的 Codex 窗口。这样可以避免 Stop hook 延迟、工具级完成事件和子 agent 完成造成误闪。

## 状态含义

- 红灯：至少有一个会话正在运行、思考、搜索或调用工具。红灯常亮。
- 绿灯：所有会话空闲或已停止。任一运行中的会话结束时，会显示 3 秒绿灯闪烁提示；如果仍有其它会话运行，提示结束后回到红灯。
- 黄灯：至少有一个会话等待用户批准、输入或介入。黄灯常亮。

优先级是：等待用户介入 > 正在运行 > 全部完成。

## 文件说明

- `indicator.py`：悬浮红绿灯窗口，只读取状态文件，不改 Codex 配置。
- `codex_status_hook.py`：给 Codex hooks 调用的状态写入脚本。
- `codex_rollout_status.py`：从 `%USERPROFILE%\.codex\sessions\**\rollout-*.jsonl` 读取 Codex 活动，作为 hooks 未触发时的红/绿兜底状态源。
- `codex_window_status.py`：通过 Win32 顶层窗口枚举记录当前能看到的 Codex 桌面窗口，作为复盘证据，不参与红/绿主状态判断。
- `codex_log_status.py`：旧的 SQLite 日志兜底实现，当前浮窗不再使用。
- `test_status_sources.py`：状态源回归测试。
- `start-indicator.bat`：双击启动悬浮窗，命令窗口只会短暂闪一下。
- `start-indicator-hidden.vbs`：双击启动悬浮窗，不显示命令窗口。
- `start-indicator-debug.bat`：调试启动，保留命令窗口以显示报错。
- `restart-indicator.bat`：重启悬浮窗，只会停止命令行包含本目录 `indicator.py` 的旧指示器进程。
- `diagnose-status.bat`：双击显示当前 rollout、hook、diagnostics 状态并暂停，便于排查亮灯原因。
- `install-user-hooks.ps1`：可选安装脚本，把 hook 配置写入 `%USERPROFILE%\.codex\hooks.json`。
- `uninstall-user-hooks.ps1`：可选卸载脚本，移除本指示器的 hook 配置。
- `hooks.example.json`：hook 配置样例，不会自动生效。
- `REPLICATION_PROMPT.zh-CN.md`：给其它 AI 使用的独立复刻提示词方案。
- `runtime\state.json`：运行时状态文件，首次运行或首次 hook 触发时自动生成。
- `runtime\events.jsonl`：hook 事件日志，便于排查状态是否准确。
- `runtime\diagnostics.json`：当前状态来源、hook 状态、rollout 状态和最近触发事件。
- `runtime\observations.jsonl`：指示器运行观测日志。启动、状态变化、active source 变化以及每 30 秒心跳都会写入一行。
- `runtime\transitions.jsonl`：只记录灯状态变化的精简日志，适合回看某个时间点为什么从红/黄/绿切到另一个颜色。
- `backups\`：安装/卸载 hooks 时自动保存的备份。

## 先本地试运行

双击以下任意一个：

```text
start-indicator.bat
start-indicator-hidden.vbs
```

`start-indicator.bat` 会用 `pythonw.exe` 后台启动，命令窗口只会短暂闪一下然后关闭。`start-indicator-hidden.vbs` 不显示命令窗口。

也可以用命令行：

```powershell
python .\indicator.py
```

如果启动失败、需要看错误信息，双击：

```text
start-indicator-debug.bat
```

如果修改过脚本或怀疑当前悬浮窗还是旧进程，双击：

```text
restart-indicator.bat
```

测试状态：

```powershell
python .\codex_status_hook.py --event UserPromptSubmit --session manual-test
python .\codex_status_hook.py --event PermissionRequest --session manual-test
python .\codex_status_hook.py --event Stop --session manual-test
```

运行回归测试：

```powershell
python .\test_status_sources.py
```

查看当前亮灯原因：

```text
diagnose-status.bat
```

## 安装到 Codex hooks

确认本地浮窗能正常打开后，再运行：

```powershell
.\install-user-hooks.ps1
```

安装脚本会：

1. 创建 `%USERPROFILE%\.codex`，如果它不存在；
2. 备份现有 `hooks.json` 到本目录的 `backups\`；
3. 只移除旧的本指示器 hook；
4. 追加新的本指示器 hook；
5. 不修改其它 hook。

Codex 可能会要求你信任新 hook。按官方文档，这是正常流程；如果 Codex 提示 hook 需要 review，请在 Codex 中打开 `/hooks` 并信任本指示器 hook。

## 卸载

运行：

```powershell
.\uninstall-user-hooks.ps1
```

卸载脚本会先备份 `hooks.json`，然后只删除命令里包含 `codex_status_hook.py` 的 hook。

如果要完全手动撤回，也可以用 `backups\` 里的备份覆盖：

```text
%USERPROFILE%\.codex\hooks.json
```

## 设计边界

这个便携版故意不使用 Codex 原生宠物状态机，因为原生宠物会受 hover、drag、内部动画行映射影响。这里优先使用官方 Codex hooks 作为状态源，同时读取本地 rollout JSONL 作为红/绿兜底状态源。浮窗本身不绑定 hover 事件。

rollout 负责判断运行/空闲，显示层将运行映射为红灯、空闲映射为绿灯。`event_msg: task_started` 会在问题提交后立即进入运行状态。hook 只负责黄灯；只有 30 分钟内的新鲜 `PermissionRequest` 状态会覆盖 rollout，因为让 hook 参与红/绿判断容易在 Stop 丢失或延迟时造成运行中误判。如果 Codex 提示 hook 需要 review，请打开 `/hooks` 并信任本指示器 hook。

显示层有一个 3 秒绿色完成提示覆盖层。`rollout.active_count` 只统计顶层对话/项目；它从 3 降到 2、2 降到 1、1 降到 0 都会触发绿闪。子 agent 仍会作为运行证据保留，但不会作为独立计数，因此子 agent 完成不会触发绿闪。绿闪结束后，如果顶层 `active_count` 仍大于 0，显示回运行红灯；如果等于 0，保持完成绿灯。黄灯优先级更高，等待授权时不会被绿闪覆盖。

工具级事件不会清空运行状态。例如 `patch_apply_end` 里的 `status: completed` 只表示一次工具调用完成，不表示整轮 Codex 任务完成；只有 `task_complete`、`turn_state` 这类 turn/task 级事件或最终 assistant message 才会让红灯转为完成绿灯。

右键红绿灯并点击 **Open diagnostics** 可以打开 `runtime\diagnostics.json`，查看当前状态来自 `hook`、`rollout` 还是 `stabilizer`。

`diagnostics.json` 里的 `rollout.active_sources` 会列出当前正在运行的全部 rollout 文件，并标记 `is_subagent` 与 `parent_thread_id`。`active_count` 是顶层活动数，`raw_active_count` 是包括子 agent 在内的原始活动数，`subagent_active_count` 是当前子 agent 数量。正常情况下，正在运行时至少有一个 active source；所有任务结束后应清空，显示 3 秒绿闪后保持绿灯。

如果运行一两天后需要复盘误判，优先看 `runtime\transitions.jsonl`。每行都会记录：

- `timestamp`：指示器本地时间。
- `activity_status`：内部判断状态，`green` 表示运行中，`red` 表示全部完成，`yellow` 表示等待授权。
- `display_status`：实际显示颜色，当前配置下运行中显示红，完成显示绿。
- `chosen`：最终采用的状态源。
- `hook`：hook 当时报告的状态。
- `rollout`：rollout 当时报告的状态和 `active_sources`。
- `windows`：当时 Windows 能枚举到的 Codex 顶层窗口快照，包括 `window_count`、`visible_count`、`foreground_count`、`hwnd`、`pid`、窗口标题、进程路径、是否最小化和窗口矩形。如果当前环境拿不到桌面窗口，会在 `windows.error` 里记录原因。

如果 `transitions.jsonl` 不够细，再看 `runtime\observations.jsonl`。它会额外记录 active source 变化和每 30 秒心跳，方便判断某个窗口是真的还在跑，还是某个旧 rollout 文件没有正确被完成事件清掉。

注意：`windows` 记录的是 OS 层“真实窗口证据”，`rollout.active_sources` 记录的是 Codex 任务/会话活动证据。两者不一定一一对应；如果两者冲突，后续排查时以 `rollout.active_sources` 判断任务是否仍在运行，以 `windows` 判断当时桌面上是否存在可见/最小化 Codex 窗口。

## 两种使用和复刻方式

### 方案一：下载项目直接使用

1. 下载或克隆本仓库。
2. Windows 准备 Python 3，并确认 `tkinter` 可用；为了获得高 DPI Pillow 渲染效果，安装 `Pillow`。
3. 双击 `start-indicator-hidden.vbs` 启动悬浮灯，或运行 `start-indicator.bat`。
4. 如需黄灯授权状态，再运行 `install-user-hooks.ps1` 安装用户级 hooks。

这个方案保留完整的状态读取、父子 agent 识别、日志和回归测试，适合直接运行或继续开发。项目不会上传个人的 `runtime\`、`backups\`、缓存和会话文件，这些目录已被 `.gitignore` 排除。

### 方案二：把复刻提示词交给其它 AI

打开 [REPLICATION_PROMPT.zh-CN.md](REPLICATION_PROMPT.zh-CN.md)，把其中的完整提示词交给目标 AI。提示词要求目标 AI 先检查 Windows、Codex rollout/hooks 格式和权限，再按本项目的状态模型、视觉约束、日志链条和测试验收标准复刻，不依赖本仓库的个人路径或运行日志。

如果目标 AI 能读取 GitHub 链接，也可以把本仓库链接和该提示词一起提供：链接用于读取实现参考，提示词用于明确复刻目标和验收边界。
