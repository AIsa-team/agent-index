#!/usr/bin/env python3
"""version_info.py — CIO self-check: installed version, index latest, update health.

Pure stdlib. Determines the running agent's content version, compares with the
public agent-index, and reads content-update-loop logs to judge updater health.
Prints a report between __REPORT_START__ / __REPORT_END__ markers, followed by
a DONE:/FAILED: status line (house style shared with the DSA scripts).

Version truth sources (priority order, per 2026-07-21 E2B field investigation):
  1. <profile>/.agentspec-content/active.json — content updater's active release
     (E2B Level-2 layout; the authoritative content version)
  2. <profile>/.agentspec.json               — install marker (agentspec-v1 §4.1)
  3. <profile>/agent.json / agent.lock.json  — artifact/dev fallbacks
Index: https://raw.githubusercontent.com/AIsa-team/agent-index/main/index.json

Profile dir resolution (priority order):
  1. argv[1]  2. $PROFILE_DIR  3. $HERMES_HOME  4. walk up from this script's
  own path to the nearest dir containing agent.json / SOUL.md / .env.example
  5. ~/.aisa/agents/cio
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
CDN_GRACE_S = 30 * 60          # index CDN cache can lag ~5-30 min after publish
LOOP_STALE_S = 15 * 60         # no loop activity for this long => loop suspect
LOG_TAIL_LINES = 8

PROFILE_ANCHOR_FILES = ("agent.json", "SOUL.md", ".env.example")


def resolve_profile_dir() -> Path:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return Path(sys.argv[1].strip()).expanduser()
    for env in ("PROFILE_DIR", "HERMES_HOME"):
        v = os.environ.get(env)
        if v:
            return Path(v).expanduser()
    # walk up from the script itself: works for both
    #   <profile>/skills/ops/version-info/scripts/version_info.py          (user skills)
    #   <profile>/.agentspec-content/current/skills/ops/.../version_info.py (managed)
    here = Path(__file__).resolve()
    for anc in here.parents:
        if any((anc / f).exists() for f in PROFILE_ANCHOR_FILES):
            return anc
    return Path("~/.aisa/agents/cio").expanduser()


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


def fmt_age(epoch: float) -> str:
    age_s = int(time.time() - epoch)
    if age_s < 0:
        return "未来时间?"
    if age_s < 3600:
        return f"{age_s // 60} 分钟前"
    if age_s < 86400:
        return f"{age_s // 3600} 小时前"
    return f"{age_s // 86400} 天前"


def fmt_ts(epoch: float) -> str:
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone()
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S %Z')}（{fmt_age(epoch)}）"


def fmt_mtime(path: Path) -> str:
    try:
        return fmt_ts(path.stat().st_mtime)
    except OSError:
        return "unreadable"


def fetch_index():
    req = urllib.request.Request(INDEX_URL, headers={"User-Agent": "aisa-cio-version-info/2"})
    try:
        with urllib.request.urlopen(req, timeout=INDEX_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except Exception as e:  # network / parse — report, never crash
        return None, f"{type(e).__name__}: {e}"


def find_update_log(pdir: Path):
    home = Path(os.environ.get("HOME", "~")).expanduser()
    for cand in (home / "content-update.log", pdir / "content-update.log",
                 pdir / "logs" / "content-update.log"):
        if cand.is_file():
            return cand
    return None


def main() -> int:
    pdir = resolve_profile_dir()
    lines = []
    ok = True

    lines.append("=== CIO 版本与更新自检 ===")
    lines.append(f"profile dir: {pdir}")
    lines.append("")

    # --- 1. local version (truth-source priority) ---
    agent_id = DEFAULT_AGENT_ID
    local_version = None
    local_source = None
    pinned = None
    updated_at = None

    active = read_json(pdir / ".agentspec-content" / "active.json")
    if active and active.get("version"):
        agent_id = active.get("agentId", agent_id)
        local_version = active["version"]
        local_source = ".agentspec-content/active.json（内容更新器 active release）"
        updated_at = active.get("updatedAt")
        lines.append(f"[本地版本] {local_version}  ← {local_source}")
        lines.append(f"  release={active.get('release')}")
        if updated_at:
            lines.append(f"  内容切换时间: {fmt_ts(updated_at)}")
        rels = pdir / ".agentspec-content" / "releases"
        if rels.is_dir():
            names = sorted(p.name for p in rels.iterdir())
            lines.append(f"  本地留存 releases: {', '.join(names[-4:])}")

    marker = read_json(pdir / ".agentspec.json")
    if marker:
        pinned = marker.get("pinned")
        if local_version is None:
            agent_id = marker.get("id", agent_id)
            local_version = marker.get("version")
            local_source = ".agentspec.json（安装 marker）"
            lines.append(f"[本地版本] {local_version}  ← {local_source}")
        lines.append(f"  marker: version={marker.get('version')}  target={marker.get('target')}  pinned={pinned}")

    if local_version is None:
        for fb_name in ("agent.json", "agent.lock.json"):
            fb = read_json(pdir / fb_name)
            if fb and fb.get("version"):
                agent_id = fb.get("agent") or fb.get("id") or agent_id
                local_version = fb["version"]
                local_source = f"{fb_name}（fallback）"
                lines.append(f"[本地版本] {local_version}  ← {local_source}")
                break
    if local_version is None:
        lines.append("[本地版本] ⚠️ 未找到任何版本信息 —— dev 环境（非安装器安装）或安装未完成。")
    lines.append("")

    # --- 2. index latest ---
    index, index_err = fetch_index()
    latest = None
    if index:
        entry = (index.get("agents") or {}).get(agent_id) or {}
        latest = entry.get("latest")
        lines.append(f"[中心索引] latest = {latest or '（索引中无 ' + agent_id + '）'}")
    else:
        ok = False
        lines.append(f"[中心索引] 拉取失败: {index_err}")
        lines.append("  ⚠️ 无法判断是否落后于 latest。")
    lines.append("")

    # --- 3. update loop health ---
    log_path = find_update_log(pdir)
    loop_recent = False
    last_status = None
    lines.append("[更新循环健康度]")
    if log_path:
        try:
            mtime = log_path.stat().st_mtime
            loop_recent = (time.time() - mtime) < LOOP_STALE_S
            tail = log_path.read_text(errors="ignore").strip().splitlines()[-LOG_TAIL_LINES:]
            lines.append(f"  日志: {log_path}  最后活动: {fmt_ts(mtime)}")
            for ln in tail:
                try:
                    j = json.loads(ln)
                    last_status = j.get("status", last_status)
                    lines.append(f"    {j.get('status','?'):9s} version={j.get('version','?')}")
                except (json.JSONDecodeError, AttributeError):
                    lines.append(f"    {ln[-120:]}")
            if not loop_recent:
                lines.append(f"  ⚠️ 循环已 {fmt_age(mtime)} 无输出（正常应 ≤ 更新间隔，默认 300s）")
        except OSError as e:
            lines.append(f"  日志读取失败: {e}")
    else:
        lines.append("  未找到 content-update.log —— 本环境可能不运行内容更新循环（如本地 dev / CLI 安装）。")
    lines.append("")

    # --- 4. verdict ---
    lines.append("[结论]")
    lk, rk = semver_key(local_version or ""), semver_key(latest or "")
    if lk and rk:
        if lk == rk:
            lines.append(f"  ✅ 本地 {local_version} == 索引 latest {latest}，已是最新。")
        elif lk < rk:
            if pinned:
                lines.append(f"  📌 本地 {local_version} < latest {latest}，但 pinned=true —— 显式钉住版本，不更新是契约行为，不是故障。")
            elif loop_recent:
                lines.append(f"  ⏳ 本地 {local_version} < latest {latest}，但更新循环活跃 —— 大概率是索引 CDN 缓存延迟（发布后 5–30 分钟属正常），稍后重查。")
                lines.append(f"     若超过 {CDN_GRACE_S // 60} 分钟仍未收敛，再查 content-update.log 中的下载/SHA 报错。")
            else:
                lines.append(f"  ⚠️ 本地 {local_version} < latest {latest}，且更新循环无近期活动 —— 更新器可能未运行或已卡死，检查 sandbox entrypoint 与 content-update.log。")
        else:
            lines.append(f"  ℹ️ 本地 {local_version} > latest {latest} —— 本地领先于索引（dev 版本或索引未发布）。")
    else:
        lines.append("  ⚠️ 版本比较不可用（本地或索引版本缺失）。")
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
