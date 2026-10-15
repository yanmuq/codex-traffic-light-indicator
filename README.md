# Codex 纯粹的状态红绿灯指示器

这是一个便携版 Windows 红绿灯指示器，用一个始终置顶的小窗口显示 Codex 任务状态。它不 patch Codex App，不替换系统文件，也不依赖原生宠物的 hover/动画状态。
它专注于状态提示，支持拖动位置、右键查看诊断和退出，没有桌宠互动功能。

## 项目做什么

它把 Codex 的多个状态来源统一成三个可见信号：

- 红灯：rollout 检测到会话正在运行、思考、搜索或调用工具，包括子 agent 的活动。
- 黄灯：hook 报告等待用户介入，并通过指示器的新鲜度判断，优先级最高。安装脚本接入的等待事件是 `PermissionRequest`。
- 绿灯：没有检测到活动会话。检测到顶层活动任务数量减少时，会显示 3 秒完成提示，期间绿灯闪烁 3 次；如果仍有会话运行，随后回到红灯。

子 agent 的运行会继续作为主对话的运行证据，但子 agent 完成不会单独触发绿灯提示。工具级的 `status: completed` 也不会被当成整轮任务完成。

## 完整工作链条

```text
Codex hooks / rollout JSONL / Win32 窗口快照
                 |
                 v
       状态源读取与事件分类
                 |
                 +--> hook: 提供等待授权黄灯和活动会话 ID
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
                 +--> 是：3 秒绿灯完成提示（黄灯优先）
                 +--> 仍有活动会话：回到红灯
                 +--> 没有活动会话：保持绿灯
                 |
                 v
       DPI 直出渲染 + diagnostics/observations/transitions 日志
```

状态源的优先顺序不是简单的“谁最后写入谁负责”：rollout 负责运行/完成，hook 只覆盖新鲜的等待授权状态，窗口枚举只用于复盘桌面上实际存在的 Codex 窗口。这样可以避免 Stop hook 延迟、工具级完成事件和子 agent 完成造成误闪。

发现 rollout 文件时，除按修改时间选择最近文件外，还会纳入 hooks 记录的运行中或等待中的会话。Windows 上持续打开的日志可能已追加新事件，但文件修改时间尚未更新；这些会话不会再被最近 24 个文件或 24 小时时间窗排除。hooks 在这里仅提供会话 ID，是否运行、是否完成仍由对应 rollout 内容判断。

## 状态含义

- 红灯：检测到会话活动时常亮；顶层活动计数下降后可以暂时显示绿色完成提示。
- 绿灯：未检测到活动会话时常亮；完成提示结束后，如果仍有活动会话则回到红灯。
- 黄灯：有效的 hook 等待状态常亮，并覆盖红灯和绿色完成提示。

优先级是：等待用户介入 > 正在运行 > 全部完成。

## 文件说明

- `indicator.py`：读取 hook 和 rollout 状态，绘制悬浮窗并写入本目录的运行诊断，不改 Codex 配置。
- `codex_status_hook.py`：给 Codex hooks 调用的状态写入脚本。
- `invoke-status-hook.ps1`：Windows hook 启动入口，用 PowerShell 调用指定的 Python 和 `codex_status_hook.py`。
- `codex_rollout_status.py`：从 `%USERPROFILE%\.codex\sessions\**\rollout-*.jsonl` 读取 Codex 活动，是红/绿状态的主要依据。
- `codex_window_status.py`：通过 Win32 顶层窗口枚举记录当前能看到的 Codex 桌面窗口，作为复盘证据，不参与红/绿主状态判断。
- `codex_log_status.py`：独立的 SQLite 日志状态读取脚本，当前浮窗不加载它。
- `test_status_sources.py`：状态源回归测试。
- `start-indicator.bat`：双击启动悬浮窗，命令窗口只会短暂闪一下。
- `start-indicator-hidden.vbs`：双击启动悬浮窗，不显示命令窗口。
- `start-indicator-debug.bat`：调试启动，保留命令窗口以显示报错。
- `restart-indicator.bat` / `restart-indicator.ps1`：停止命令行包含本目录 `indicator.py` 的指示器进程，再通过隐藏启动脚本重启。
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

准备 Python **3.11 或更新版本**，并确认该解释器带有 `tkinter`。`Pillow` 是可选依赖：安装后使用 Pillow 绘制高 DPI 灯面，未安装时使用 Tk Canvas。可在选定的 Python 环境中运行 `python -m pip install Pillow`。

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

### Python 与 Tcl/Tk 路径

启动脚本会尝试预设的 `C:\Python313`、项目内的 `python-runtime-release` 或 PATH 中的 Python。各入口的查找顺序不同，`.bat` 和 hook 安装脚本还包含 Codex 缓存运行时的候选路径；仓库本身不附带 Python。需要指定解释器时，使用实际存在的完整路径：

| 环境变量 | 用途 |
| --- | --- |
| `CODEX_TRAFFIC_LIGHT_PYTHON` | 调试启动脚本使用的 `python.exe`；hook 安装脚本读取同名的**用户级**环境变量。 |
| `CODEX_TRAFFIC_LIGHT_PYTHONW` | 普通和隐藏启动脚本使用的 `pythonw.exe`。 |
| `CODEX_TRAFFIC_LIGHT_TCL_LIBRARY` | 对应解释器的 Tcl 库目录，例如 `tcl\tcl8.6`。 |
| `CODEX_TRAFFIC_LIGHT_TK_LIBRARY` | 对应解释器的 Tk 库目录，例如 `tcl\tk8.6`。 |

通过 Windows 用户环境变量设置保存后，重新打开终端再启动。Tcl/Tk 两个变量应配套设置，并与选用的 Python 匹配；正常安装且能直接运行 `python .\indicator.py` 时，无需另外设置。仅修改当前 PowerShell 的 `$env:CODEX_TRAFFIC_LIGHT_PYTHON` 不会改变 hook 安装脚本读取的用户级值。

hook 安装脚本按以下顺序选择解释器：用户级 `CODEX_TRAFFIC_LIGHT_PYTHON` → 项目内运行时 → `C:\Python313\python.exe` → Codex 缓存运行时 → PATH。安装后，完整路径会写入 hook 配置；移动项目或更换 Python 后需要重新运行安装脚本。

### 操作与诊断

按住左键可以拖动浮窗；右键菜单提供 **Open diagnostics**、**Open runtime folder** 和 **Exit**，窗口获得键盘焦点时也可按 `Esc` 退出。

Windows 上每秒维护一次置顶状态，在窗口显示、拖动结束及右键菜单操作后也会重新置顶。Win32 置顶调用使用不激活窗口的标志，避免定时刷新抢走当前输入焦点。

如果启动失败、需要看错误信息，双击：

```text
start-indicator-debug.bat
```

如果修改过脚本或怀疑当前悬浮窗还是旧进程，双击：

```text
restart-indicator.bat
```

测试 hook 写入和等待提示（先进入项目目录）：

```powershell
'{}' | python .\codex_status_hook.py --event UserPromptSubmit --session manual-test --print-state
'{}' | python .\codex_status_hook.py --event PermissionRequest --session manual-test --print-state
'{}' | python .\codex_status_hook.py --event Stop --session manual-test --print-state
```

每条命令单独运行，通过管道提供空 JSON，避免脚本等待终端输入。第一条写入测试会话，第二条触发黄灯，第三条清除该测试会话。hook 的运行/停止记录不直接决定红绿，`Stop` 后浮窗恢复显示实际会话状态；红绿切换应结合真实 Codex 任务或下面的回归测试检查。

运行回归测试：

```powershell
python .\test_status_sources.py
```

查看当前亮灯原因：

```text
diagnose-status.bat
```

这个诊断脚本直接调用 PATH 中的 `python`。它单独执行的 rollout 探针不带 hook 会话 ID 提示，因此排查仍在运行的旧会话时，以浮窗写出的 `runtime\diagnostics.json` 为准。

## 安装到 Codex hooks

确认本地浮窗能正常打开后，再运行：

```powershell
.\install-user-hooks.ps1
```

可先用 `.\install-user-hooks.ps1 -DryRun` 查看将写入的配置，不落盘。

安装脚本会：

1. 创建 `%USERPROFILE%\.codex`，如果它不存在；
2. 备份现有 `hooks.json` 到本目录的 `backups\`；
3. 只移除旧的本指示器 hook；
4. 追加新的本指示器 hook；
5. 不修改其它 hook。

脚本为 `SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`PermissionRequest` 和 `Stop` 六类事件安装指示器处理器。Windows 的 `commandWindows` 通过 `powershell.exe -NoProfile -NonInteractive -File` 调用 `invoke-status-hook.ps1`，再调用选定的 Python；Python 按 UTF-8 解码管道输入，安装和卸载脚本以无 BOM 的 UTF-8 保存 JSON。

如果 Codex 提示 hook 需要 review，按应用提示审核并信任本指示器命令。

## 卸载

运行：

```powershell
.\uninstall-user-hooks.ps1
```

卸载脚本会先备份 `hooks.json`，然后只删除命令里包含 `codex_status_hook.py` 的 hook。

可先运行 `.\uninstall-user-hooks.ps1 -DryRun` 预览。移除 hooks 不会关闭已启动的浮窗；需要停止指示器时，在右键菜单中选择 **Exit**。

如果要完全手动撤回，也可以用 `backups\` 里的备份覆盖：

```text
%USERPROFILE%\.codex\hooks.json
```

## 设计边界

浮窗本身不绑定 hover 事件，也不依赖 Codex 原生宠物状态机。rollout 是运行/空闲状态的主要依据；hooks 提供等待提示和活动会话 ID；Win32 窗口枚举仅记录窗口证据。

rollout 负责判断运行/空闲，显示层将运行映射为红灯、空闲映射为绿灯。读到 `event_msg: task_started` 时进入运行状态。hook 黄灯使用快照中的 `age_seconds` 与 30 分钟阈值判断是否覆盖 rollout，hook 的运行/停止状态不直接决定红绿。

显示层有一个 3 秒绿色完成提示覆盖层。`rollout.active_count` 只统计顶层对话/项目；检测到它从 3 降到 2、2 降到 1、1 降到 0 都会触发绿闪。子 agent 仍作为运行证据保留，但不作为独立计数，因此子 agent 完成不会单独触发绿闪。绿闪结束后，只要仍有活动 rollout（包括子 agent），就回到运行红灯；没有活动会话则保持绿灯。黄灯优先级更高，等待授权时不会被绿闪覆盖。

默认每 300 毫秒刷新显示，每 1.5 秒重新发现 rollout 文件；hook 会话 ID 集合变化时也会重新发现。活动事件超过 15 分钟没有更新时，该 rollout 会被判为空闲。指示器根据这些本地记录推断状态，并不直接读取 Codex 服务端任务状态。

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
2. Windows 准备 Python 3.11 或更新版本，并确认 `tkinter` 可用；为了获得高 DPI Pillow 渲染效果，可安装 `Pillow`。
3. 双击 `start-indicator-hidden.vbs` 启动悬浮灯，或运行 `start-indicator.bat`。
4. 运行 `install-user-hooks.ps1` 接入黄灯授权提示，并为 rollout 发现提供活动会话 ID。

这个方案保留完整的状态读取、父子 agent 识别、日志和回归测试，适合直接运行或继续开发。项目不会上传个人的 `runtime\`、`backups\`、缓存和会话文件，这些目录已被 `.gitignore` 排除。

### 方案二：把复刻提示词交给其它 AI

打开 [REPLICATION_PROMPT.zh-CN.md](REPLICATION_PROMPT.zh-CN.md)，把其中的完整提示词交给目标 AI。提示词要求目标 AI 先检查 Windows、Codex rollout/hooks 格式和权限，再按本项目的状态模型、视觉约束、日志链条和测试验收标准复刻，不依赖本仓库的个人路径或运行日志。

如果目标 AI 能读取 GitHub 链接，也可以把本仓库链接和该提示词一起提供：链接用于读取实现参考，提示词用于明确复刻目标和验收边界。

## 许可证

本项目采用 [MIT License](LICENSE)。你可以自由使用、复制、修改、商用和再发布，但需要保留版权声明和许可证文本。项目按“现状”提供，不对运行结果或适用性作担保。
