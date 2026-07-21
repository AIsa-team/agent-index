---
name: version-info
description: "AUTO-INVOKE when user asks about the agent's version or update status. Triggers: version / 版本 / 版本信息 / update status / 更新状态 / self check / 自检. Reports installed version, index latest, pinned state, and update-loop health evidence."
---

## MANDATORY ROUTING RULE

When the user asks any of: `version`, `版本`, `版本信息`, `你是哪个版本`, `update status`, `更新状态`, `自动更新正常吗`, `self check`, `自检` — you MUST run the script below and deliver its output. Do NOT answer version questions from memory: your session's system prompt is a snapshot from session creation and may be OLDER than what is on disk.

## How to invoke

Run via `execute_code`:

```python
import subprocess, sys
result = subprocess.run(
    [sys.executable, "${PLUGIN_ROOT}/skills/ops/version-info/scripts/version_info.py"],
    capture_output=True, text=True, timeout=60,
)
print(result.stdout)
sys.stderr.write(result.stderr)
```

The script is pure stdlib (no venv required). It needs network access to fetch the public index; if that fails it still reports local info and says so.

## OUTPUT RULE

The script prints the full report between `__REPORT_START__` and `__REPORT_END__`, followed by a `DONE:`/`FAILED:` status line. Reply with the text between the markers **verbatim** — no paraphrasing, no summarizing. You MAY append a short interpretation after the report (e.g. what the verdict means for the user), clearly separated from it.

## What it reports

1. **本地已安装版本** — `$PROFILE_DIR/.agentspec.json` install marker（id / version / target / pinned）；marker 缺失时 fallback 到 `agent.json` / `agent.lock.json`，都没有则明确说这是 dev 环境或安装未完成。
2. **索引 latest** — 拉取 `https://raw.githubusercontent.com/AIsa-team/agent-index/main/index.json` 比较。
3. **结论** — 已最新 / 落后（含 pinned 判别：pinned=true 时不更新是契约行为，不是故障）/ 本地领先。
4. **更新循环活动痕迹** — probe 常见状态文件/目录的存在性和 mtime，作为更新器是否在运行的旁证。
5. **会话缓存提示** — 内容更新从下一会话生效；磁盘新版 ≠ 当前会话新版。

## Interpretation guide (for you, the agent)

- 本地 < latest 且 `pinned=false` 且持续多个更新周期（默认 300s/次）→ 更新循环可能挂了，建议用户查 sandbox entrypoint 更新日志。
- 本地 < latest 且 `pinned=true` → 显式钉住，符合预期。
- 用户说"更新了但行为没变" → 先看 [重要提示]：极可能是磁盘已更新、会话未重建。让用户开新会话再验证。
- 无 marker → 本机不是安装器安装的（dev checkout），版本问题应到发布环境验证。
