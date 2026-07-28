# Codex 红绿灯指示器复刻提示词

把下面的内容交给另一个 AI，用于在 Windows 上复刻一个 Codex 任务状态红绿灯。目标 AI 可以先阅读本 GitHub 项目，也可以只使用这份提示词独立实现。

```text
你是一名负责 Windows 本地工具的资深工程师。请在当前机器上复刻一个 Codex 任务状态红绿灯。先检查环境、Codex 版本、Python/Tk/Pillow、hooks 配置和 rollout JSONL 的实际格式，再开始改文件；不要凭理论猜测事件语义。

一、目标行为

1. 红灯表示至少有一个顶层 Codex 对话/项目正在运行、思考、搜索或调用工具。
2. 绿灯表示所有顶层任务空闲或完成。
3. 黄灯表示至少有一个任务等待用户批准、输入或介入；黄灯优先级最高。
4. 红灯和黄灯平时常亮，不做呼吸闪烁。
5. 当任一顶层任务完成时，绿灯闪烁 3 秒：如果仍有顶层任务运行，3 秒后回红灯；如果全部完成，保持绿灯。
6. 子 agent 的运行可以作为主对话仍在运行的证据，但子 agent 完成不能单独触发绿灯闪烁。
7. 工具级事件，例如 patch_apply_end 的 status=completed，只表示一次工具调用完成，不表示整轮任务完成。

二、状态来源

1. 优先读取 Codex 官方 hooks 事件，但 hook 只负责新鲜的 PermissionRequest/等待介入黄灯，不负责决定红绿。
2. 读取 Codex 本地 sessions 目录中的 rollout-*.jsonl，识别 reasoning、function_call、function_call_output、custom_tool_call、custom_tool_call_output、task_started 等运行事件。
3. 只有 task_complete、turn_aborted、turn_state 的任务级完成状态，或者最终 assistant message，才能清除顶层任务运行状态。
4. 读取 session_meta.payload.parent_thread_id，识别子 agent。所有 active rollout 可以保留在诊断证据中，但完成闪烁计数只统计没有 parent_thread_id 的顶层 rollout。
5. 通过 Win32 枚举 Codex 顶层窗口，记录窗口标题、PID、位置、可见性和前台状态。窗口快照用于日志复盘，不直接替代 rollout 状态。

三、状态仲裁

1. 先计算所有 active rollout，保留 raw_active_count。
2. 再计算顶层 active_count；子 agent 不增加这个计数。
3. 有新鲜黄灯时显示黄灯，并暂停/取消绿灯完成提示。
4. 没有黄灯时，只要任意 rollout active 就显示运行红灯；全部 rollout 都不 active 才显示空闲绿灯。
5. 只有顶层 active_count 下降才启动 3 秒绿灯提示。子 agent 完成造成的 raw_active_count 下降不能启动提示。

四、视觉和 DPI 要求

1. 使用一个始终置顶、可拖动、无标题栏的小窗口。
2. 保持交通灯外壳原本的窄长比例和适度圆角，不要把外壳做成过度圆润的胶囊。
3. Windows 启用 Per-Monitor DPI 感知，按当前 DPI 直接生成物理像素尺寸的图像；不要把 72x106 的低分辨率图像交给 Windows 放大，也不要高分辨率绘制后再缩回低分辨率。
4. 透明色窗口不能依赖半透明边缘，否则容易出现黑色或灰色毛刺。优先使用清晰的不透明像素和 DPI 直出。
5. 红灯、黄灯不做常态闪烁；只对 3 秒完成提示做绿灯闪烁。

五、日志和诊断

至少生成：

- diagnostics.json：当前状态源、hook 状态、rollout 状态、顶层 active_count、raw_active_count、subagent_active_count。
- observations.jsonl：启动、状态源变化、窗口快照、子 agent 标记和心跳。
- transitions.jsonl：实际显示颜色变化、触发原因、active source 列表和 parent_thread_id。

不要把真实用户路径、session 内容、cookie、token、API key 或个人运行日志提交到公开仓库。运行日志、备份、缓存和 __pycache__ 必须加入 .gitignore。

六、实现和验收

1. 先备份将要修改的文件。
2. 保留用户已有改动，不覆盖无关文件。
3. 增加回归测试，至少覆盖：task_started 立即变为运行、工具级 completed 不清除运行、父任务完成触发绿闪、部分顶层任务完成后回红、子 agent 完成不改变顶层 active_count、黄灯覆盖绿闪。
4. 运行 Python 语法检查和全部回归测试。
5. 用真实本地 diagnostics 和 transitions 检查一次，不要只声称“理论上可用”。
6. 报告修改文件、备份位置、测试命令、实际结果和仍未验证的边界。

交付内容应包括：可运行的 Windows 文件、中文 README、完整状态工作流说明、独立复刻提示词、安装/卸载说明、日志说明和安全的公开仓库筛选规则。
```

使用这份提示词时，目标 AI 仍然需要根据实际 Codex 版本重新核验事件字段，不要把本提示词中的本地路径、会话 ID 或历史日志当作目标机器的事实。
