#!/usr/bin/env python3
"""version_info.py — CIO self-check: installed version, index latest, update health.

Pure stdlib. Reads the AgentSpec install marker, compares with the public
agent-index, and probes for update-loop activity evidence. Prints a report
between __REPORT_START__ / __REPORT_END__ markers, followed by a DONE:/FAILED:
status line (house style shared with the DSA scripts).

Data sources (in priority order):
  1. $PROFILE_DIR/.agentspec.json   — install marker (agentspec-v1 §4.1)
  2. $PROFILE_DIR/agent.json        — artifact-carried manifest snapshot
  3. $PROFILE_DIR/agent.lock.json   — build lock (dev checkouts)
  4. https://raw.githubusercontent.com/AIsa-team/agent-index/main/index.json
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

INDEX_URL = "https://raw.githubusercontent.com/AIsa-team/agent-index/main/index.json"
INDEX_TIMEOUT_S = 15
DEFAULT_AGENT_ID = "cio"

# Candidate files/dirs whose presence + mtime are evidence of update-loop activity.
UPDATE_EVIDENCE_CANDIDATES = [
    ".update-state.json",
    ".agent-update.log",
    "updates",
    "releases",
    "current",
    "logs",
]


def profile_dir() -> Path:
    raw = os.environ.get("PROFILE_DIR") or "~/.aisa/agents/cio"
    if len(sys.argv) > 1 and sys.argv[1].strip():
        raw = sys.argv[1].strip()
    return Path(raw).expanduser()


def read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def semver_key(v: str):
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except (ValueError, AttributeError):
        return None


def fmt_mtime(path: Path) -> str:
    try:
        ts = path.stat().st_mtime
    except OSError:
        return "unreadable"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    age_s = int(time.time() - ts)
    if age_s < 3600:
        age = f"{age_s // 60} 分钟前"
    elif age_s < 86400:
        age = f"{age_s // 3600} 小时前"
    else:
        age = f"{age_s // 86400} 天前"
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S %Z')}（{age}）"


def fetch_index():
    req = urllib.request.Request(INDEX_URL, headers={"User-Agent": "aisa-cio-version-info/1"})
    try:
        with urllib.request.urlopen(req, timeout=INDEX_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except Exception as e:  # network / parse — report, never crash
        return None, f"{type(e).__name__}: {e}"


def main() -> int:
    pdir = profile_dir()
    lines = []
    ok = True

    lines.append("=== CIO 版本与更新自检 ===")
    lines.append(f"PROFILE_DIR: {pdir}")
    lines.append("")

    # --- 1. local installed version ---
    agent_id = DEFAULT_AGENT_ID
    local_version = None
    pinned = None
    marker = read_json(pdir / ".agentspec.json")
    if marker:
        agent_id = marker.get("id", agent_id)
        local_version = marker.get("version")
        pinned = marker.get("pinned")
        lines.append("[本地安装 marker] .agentspec.json")
        lines.append(f"  id={agent_id}  version={local_version}  target={marker.get('target')}  pinned={pinned}")
        lines.append(f"  marker 写入时间: {fmt_mtime(pdir / '.agentspec.json')}")
    else:
        lines.append("[本地安装 marker] .agentspec.json 不存在")
        for fb_name in ("agent.json", "agent.lock.json"):
            fb = read_json(pdir / fb_name)
            if fb and fb.get("version"):
                agent_id = fb.get("agent") or fb.get("id") or agent_id
                local_version = fb["version"]
                lines.append(f"  fallback {fb_name}: version={local_version}")
                break
        if local_version is None:
            lines.append("  ⚠️ 未找到任何本地版本信息 —— 这通常是 dev 环境（非安装器安装），")
            lines.append("     或安装未完成（marker 只在全部必需步骤成功后写入）。")
    lines.append("")

    # --- 2. index latest ---
    index, index_err = fetch_index()
    latest = None
    if index:
        entry = (index.get("agents") or {}).get(agent_id) or {}
        latest = entry.get("latest")
        lines.append(f"[中心索引] {INDEX_URL}")
        lines.append(f"  {agent_id} latest = {latest or '（索引中无此 agent）'}")
    else:
        ok = False
        lines.append(f"[中心索引] 拉取失败: {index_err}")
        lines.append("  ⚠️ 无法判断是否落后于 latest。")
    lines.append("")

    # --- 3. verdict ---
    lines.append("[结论]")
    lk, rk = semver_key(local_version or ""), semver_key(latest or "")
    if lk and rk:
        if lk == rk:
            lines.append(f"  ✅ 本地 {local_version} == 索引 latest {latest}，已是最新。")
        elif lk < rk:
            if pinned:
                lines.append(f"  📌 本地 {local_version} < latest {latest}，但 pinned=true —— 自动更新按契约不会收敛，这是显式钉住，不是故障。")
            else:
                lines.append(f"  ⚠️ 本地 {local_version} < latest {latest} 且未 pinned —— 若超过一个更新周期（默认 300s）仍未收敛，更新循环可能异常。")
        else:
            lines.append(f"  ℹ️ 本地 {local_version} > latest {latest} —— 本地领先于索引（dev 版本或索引未发布）。")
    else:
        lines.append("  ⚠️ 版本比较不可用（本地或索引版本缺失）。")
    lines.append("")

    # --- 4. update-loop evidence ---
    lines.append("[更新循环活动痕迹]（存在性 + mtime，仅供判断更新器是否在动）")
    found_any = False
    for name in UPDATE_EVIDENCE_CANDIDATES:
        p = pdir / name
        if p.exists() or p.is_symlink():
            found_any = True
            kind = "symlink" if p.is_symlink() else ("dir" if p.is_dir() else "file")
            extra = f" -> {os.readlink(p)}" if p.is_symlink() else ""
            lines.append(f"  {name} [{kind}]{extra}  mtime: {fmt_mtime(p)}")
    if not found_any:
        lines.append("  （未发现候选痕迹文件 —— 本环境可能不运行 sandbox 更新循环，或状态文件路径与候选名不符）")
    lines.append("")

    # --- 5. session caveat ---
    lines.append("[重要提示]")
    lines.append("  内容更新不重启运行时：已有会话继续使用创建时的 system prompt，")
    lines.append("  新版 SOUL/skills 从下一个会话生效。磁盘已是新版 ≠ 当前会话是新版。")
    lines.append("  验证新版行为请开新会话。")

    print("__REPORT_START__")
    print("\n".join(lines))
    print("__REPORT_END__")
    print(("DONE: version-info" if ok else "FAILED: index fetch error (local info above still valid)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
