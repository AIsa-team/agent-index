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

1. **本地版本**（真源优先级）— `.agentspec-content/active.json`（E2B 内容更新器的 active release，最权威）→ `.agentspec.json` install marker（含 pinned）→ `agent.json` / `agent.lock.json` fallback；都没有则明确说这是 dev 环境或安装未完成。profile 目录自动推导：`PROFILE_DIR` env → `HERMES_HOME` env → 从脚本自身路径向上找 → `~/.aisa/agents/cio`。
2. **索引 latest** — 拉取 `https://raw.githubusercontent.com/AIsa-team/agent-index/main/index.json` 比较。
3. **更新循环健康度** — 读 `content-update.log`（`$HOME` 或 profile 下）尾部各轮 status + 最后活动时间，直接判断循环是否活着。
4. **结论** — 已最新 / 落后（区分三种原因：pinned 契约行为 / 循环活跃时的 CDN 缓存延迟 / 循环停摆的真故障）/ 本地领先。
5. **会话缓存提示** — 内容更新从下一会话生效；磁盘新版 ≠ 当前会话新版。

## Interpretation guide (for you, the agent)

- 本地 < latest 且循环**活跃**（日志 15 分钟内有输出）→ 大概率索引 CDN 缓存延迟（发布后 5–30 分钟属正常），让用户稍后重查，不要报故障。
- 本地 < latest 且循环**无近期活动** → 更新器可能未运行或卡死，查 sandbox entrypoint 与 `content-update.log` 报错行。
- 本地 < latest 且 `pinned=true` → 显式钉住，符合预期。
- 用户说"更新了但行为没变" → 先看 [重要提示]：极可能是磁盘已更新、会话未重建。让用户开新会话再验证。
- 无任何版本文件 → 本机不是安装器安装的（dev checkout），版本问题应到发布环境验证。
