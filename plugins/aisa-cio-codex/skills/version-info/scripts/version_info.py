#!/usr/bin/env python3
"""version_info.py — AgentSpec self-check: installed version, index latest, update health.

Pure stdlib. Determines the running agent's content version, compares with the
public agent-index, and reads content-update-loop logs to judge updater health.
Prints a report between __REPORT_START__ / __REPORT_END__ markers, followed by
a DONE:/FAILED: status line (house style shared with the DSA scripts).

Version truth sources (priority order, per 2026-07-21 E2B field investigation):
  1. <profile>/.agentspec-content/active.json — content updater's active release
     (E2B Level-2 layout; the authoritative content version)
  2. <profile>/.agentspec.json               — install marker (agentspec-v1 §4.1)
  3. <profile>/agent.json / agent.lock.json  — artifact/dev fallbacks
Index: $AGENT_INDEX_URL, defaulting to the public AIsa agent-index.

Profile dir resolution (priority order):
  1. argv[1]  2. $PROFILE_DIR  3. $HERMES_HOME  4. walk up from this script's
  own path to the nearest dir containing agent.json / SOUL.md / .env.example
  5. ~/.hermes/profiles/$PROFILE_ID  6. ~/.aisa/agents/$AGENT_SPEC_ID
"""

import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_INDEX_URL = "https://raw.githubusercontent.com/AIsa-team/agent-index/main/index.json"
INDEX_TIMEOUT_S = 15
CDN_GRACE_S = 30 * 60          # index CDN cache can lag ~5-30 min after publish
LOOP_STALE_S = 15 * 60         # no loop activity for this long => loop suspect
LOG_TAIL_LINES = 8
AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

PROFILE_ANCHOR_FILES = ("agent.json", "SOUL.md", ".env.example")


def profile_has_metadata(path: Path) -> bool:
    return (any((path / f).exists() for f in PROFILE_ANCHOR_FILES)
            or (path / ".agentspec.json").is_file()
            or (path / ".agentspec-content" / "active.json").is_file())


def resolve_profile_dir() -> Path:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return Path(sys.argv[1].strip()).expanduser()
    profile_dir = os.environ.get("PROFILE_DIR", "").strip()
    if profile_dir:
        return Path(profile_dir).expanduser()
    # Hermes itself exports HERMES_HOME as the active profile. The updater CLI
    # also uses HERMES_HOME, but there it can mean the ~/.hermes root. Accept it
    # directly only when it actually looks like a profile.
    hermes_home_raw = os.environ.get("HERMES_HOME", "").strip()
    hermes_home = Path(hermes_home_raw).expanduser() if hermes_home_raw else None
    if hermes_home and profile_has_metadata(hermes_home):
        return hermes_home
    # walk up from the script itself: works for both
    #   <profile>/skills/version-info/scripts/version_info.py              (user skills)
    #   <profile>/.agentspec-content/current/skills/version-info/.../version_info.py (managed)
    here = Path(__file__).resolve()
    for anc in here.parents:
        if profile_has_metadata(anc):
            return anc
    profile_id = (valid_agent_id(os.environ.get("PROFILE_ID"))
                  or valid_agent_id(os.environ.get("AGENT_SPEC_ID")))
    if profile_id:
        hermes_root = hermes_home or (Path.home() / ".hermes")
        candidate = hermes_root / "profiles" / profile_id
        if profile_has_metadata(candidate):
            return candidate
        # Preserve a useful incomplete-install path without treating an
        # unvalidated HERMES_HOME root as the profile itself.
        return candidate
    agent_id = env_agent_id()
    if agent_id:
        return Path.home() / ".aisa" / "agents" / agent_id
    # Deliberately do not guess a concrete Agent. The normal installed/baked
    # layouts are found above; this sentinel makes incomplete dev setups loud.
    return Path.home() / ".aisa" / "agents" / "unknown-agent"


def valid_agent_id(value):
    if isinstance(value, str):
        value = value.strip()
        if AGENT_ID_RE.fullmatch(value):
            return value
    return None


def env_agent_id():
    return (valid_agent_id(os.environ.get("AGENT_SPEC_ID"))
            or valid_agent_id(os.environ.get("PROFILE_ID")))


def resolve_index_url() -> str:
    return os.environ.get("AGENT_INDEX_URL", "").strip() or DEFAULT_INDEX_URL


def read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
            return value if isinstance(value, dict) else None
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
        return "in the future?"
    if age_s < 3600:
        return f"{age_s // 60} min ago"
    if age_s < 86400:
        return f"{age_s // 3600} h ago"
    return f"{age_s // 86400} d ago"


def fmt_ts(epoch: float) -> str:
    try:
        dt = datetime.fromtimestamp(float(epoch), tz=timezone.utc).astimezone()
        return f"{dt.strftime('%Y-%m-%d %H:%M:%S %Z')} ({fmt_age(float(epoch))})"
    except (TypeError, ValueError, OSError, OverflowError):
        return f"invalid timestamp ({epoch!r})"


def fmt_mtime(path: Path) -> str:
    try:
        return fmt_ts(path.stat().st_mtime)
    except OSError:
        return "unreadable"


def fetch_index(index_url: str, agent_id):
    user_agent_id = agent_id or "aisa-agent"
    try:
        req = urllib.request.Request(index_url, headers={"User-Agent": f"{user_agent_id}-version-info/3"})
        with urllib.request.urlopen(req, timeout=INDEX_TIMEOUT_S) as resp:
            value = json.loads(resp.read().decode("utf-8"))
            if not isinstance(value, dict):
                return None, "ValueError: index root must be a JSON object"
            agents = value.get("agents")
            if not isinstance(agents, dict):
                return None, "ValueError: index.agents must be a JSON object"
            entry = agents.get(agent_id, {})
            if not isinstance(entry, dict):
                return None, f"ValueError: index entry for {agent_id} must be a JSON object"
            latest = entry.get("latest")
            if latest is not None and not isinstance(latest, str):
                return None, f"ValueError: index latest for {agent_id} must be a string"
            return value, None
    except Exception as e:  # network / parse — report, never crash
        # Exception strings from urllib can repeat the full URL, including a
        # private deployment's signed query parameters. Keep only the class.
        return None, f"{type(e).__name__}: request or parse failed"


def find_update_log(pdir: Path):
    home = Path(os.environ.get("HOME", "~")).expanduser()
    for cand in (home / "content-update.log", pdir / "content-update.log",
                 pdir / "logs" / "content-update.log"):
        if cand.is_file():
            return cand
    return None


def main() -> int:
    pdir = resolve_profile_dir()
    index_url = resolve_index_url()
    lines = ["", f"profile dir: {pdir}", ""]
    ok = True

    # --- 1. local version (truth-source priority) ---
    agent_id = None
    identity_evidence = []
    local_version = None
    local_source = None
    pinned = None
    updated_at = None

    active = read_json(pdir / ".agentspec-content" / "active.json")
    if active and active.get("version"):
        active_id = valid_agent_id(active.get("agentId"))
        if active_id:
            identity_evidence.append(("active.json", active_id))
        agent_id = active_id
        local_version = active["version"]
        local_source = ".agentspec-content/active.json (content updater active release)"
        updated_at = active.get("updatedAt")
        lines.append(f"[local version] {local_version}  ← {local_source}")
        lines.append(f"  release={active.get('release')}")
        if updated_at is not None:
            lines.append(f"  content switch time: {fmt_ts(updated_at)}")
        rels = pdir / ".agentspec-content" / "releases"
        if rels.is_dir():
            names = sorted(p.name for p in rels.iterdir())
            lines.append(f"  locally retained releases: {', '.join(names[-4:])}")

    marker = read_json(pdir / ".agentspec.json")
    if marker:
        marker_id = valid_agent_id(marker.get("id"))
        if marker_id:
            identity_evidence.append((".agentspec.json", marker_id))
        if agent_id is None:
            agent_id = marker_id
        if local_version is None:
            pinned = marker.get("pinned")
            local_version = marker.get("version")
            local_source = ".agentspec.json (install marker)"
            lines.append(f"[local version] {local_version}  ← {local_source}")
        lines.append(f"  marker: version={marker.get('version')}  target={marker.get('target')}  pinned={pinned}")

    if local_version is None:
        for fb_name in ("agent.json", "agent.lock.json"):
            fb = read_json(pdir / fb_name)
            if fb and fb.get("version"):
                fallback_id = valid_agent_id(fb.get("agent")) or valid_agent_id(fb.get("id"))
                if fallback_id:
                    identity_evidence.append((fb_name, fallback_id))
                if agent_id is None:
                    agent_id = fallback_id
                local_version = fb["version"]
                local_source = f"{fb_name} (fallback)"
                lines.append(f"[local version] {local_version}  ← {local_source}")
                break
    # Version may already have come from active/marker while that record omitted
    # an id. Continue the same metadata priority solely to fill the missing id.
    if agent_id is None:
        for fb_name in ("agent.json", "agent.lock.json"):
            fb = read_json(pdir / fb_name)
            if fb:
                fallback_id = valid_agent_id(fb.get("agent")) or valid_agent_id(fb.get("id"))
                if fallback_id:
                    identity_evidence.append((fb_name, fallback_id))
                agent_id = fallback_id
                if agent_id:
                    break
    for env_name in ("AGENT_SPEC_ID", "PROFILE_ID"):
        candidate_id = valid_agent_id(os.environ.get(env_name))
        if candidate_id:
            identity_evidence.append((f"${env_name}", candidate_id))
    agent_id = agent_id or env_agent_id()
    if local_version is None:
        lines.append("[local version] ⚠️ no version info found — dev environment (not installer-installed) or install incomplete.")
    distinct_ids = {value for _, value in identity_evidence}
    if len(distinct_ids) > 1:
        evidence = ", ".join(f"{source}={value}" for source, value in identity_evidence)
        lines.append(f"[identity warning] conflicting Agent IDs ({evidence}); using {agent_id} by metadata priority.")
    lines.append("")
    lines[0] = f"=== {agent_id or 'unknown Agent'} version & update self-check ==="

    # --- 2. index latest ---
    index = None
    index_err = None
    latest = None
    index_source = "custom AGENT_INDEX_URL" if os.environ.get("AGENT_INDEX_URL", "").strip() else DEFAULT_INDEX_URL
    # Never echo a custom URL: private deployments may carry signed query
    # parameters or embedded credentials.
    lines.append(f"[central index] source = {index_source}")
    if agent_id:
        index, index_err = fetch_index(index_url, agent_id)
    else:
        index_err = "agent id unavailable (set AGENT_SPEC_ID or install valid AgentSpec metadata)"
    if index is not None:
        entry = (index.get("agents") or {}).get(agent_id) or {}
        latest = entry.get("latest")
        lines.append(f"  latest = {latest or '(' + agent_id + ' not in index)'}")
    else:
        ok = False
        lines.append(f"  fetch failed: {index_err}")
        lines.append("  ⚠️ cannot determine whether behind latest.")
    lines.append("")

    # --- 3. update loop health ---
    log_path = find_update_log(pdir)
    loop_recent = False
    last_status = None
    lines.append("[update loop health]")
    if log_path:
        try:
            mtime = log_path.stat().st_mtime
            loop_recent = (time.time() - mtime) < LOOP_STALE_S
            tail = log_path.read_text(errors="ignore").strip().splitlines()[-LOG_TAIL_LINES:]
            lines.append(f"  log: {log_path}  last activity: {fmt_ts(mtime)}")
            for ln in tail:
                try:
                    j = json.loads(ln)
                    last_status = str(j.get("status", last_status or "?"))
                    lines.append(f"    {last_status:9s} version={j.get('version','?')}")
                except (json.JSONDecodeError, AttributeError):
                    lines.append(f"    {ln[-120:]}")
            if not loop_recent:
                lines.append(f"  ⚠️ loop has had no output for {fmt_age(mtime)} (normally should be <= update interval, default 300s)")
        except OSError as e:
            lines.append(f"  log read failed: {e}")
    else:
        lines.append("  content-update.log not found — this environment may not run the content-update loop (e.g. local dev / CLI install).")
    lines.append("")

    # --- 4. verdict ---
    lines.append("[verdict]")
    lk, rk = semver_key(local_version or ""), semver_key(latest or "")
    if lk and rk:
        if lk == rk:
            lines.append(f"  ✅ local {local_version} == index latest {latest} — up to date.")
        elif lk < rk:
            if pinned:
                lines.append(f"  📌 local {local_version} < latest {latest}, but pinned=true — explicitly pinned; not updating is contractual, not a fault.")
            elif loop_recent:
                lines.append(f"  ⏳ local {local_version} < latest {latest}, but the update loop is active — most likely index CDN cache lag (5-30 min after publish is normal); recheck shortly.")
                lines.append(f"     If it hasn't converged after {CDN_GRACE_S // 60} min, check content-update.log for download/SHA errors.")
            else:
                lines.append(f"  ⚠️ local {local_version} < latest {latest}, and the update loop has no recent activity — the updater may not be running or is stuck; check the sandbox entrypoint and content-update.log.")
        else:
            lines.append(f"  ℹ️ local {local_version} > latest {latest} — local is ahead of the index (dev version or index not yet published).")
    else:
        lines.append("  ⚠️ version comparison unavailable (local or index version missing).")
    lines.append("")

    # --- 5. session caveat ---
    lines.append("[important note]")
    lines.append("  Content updates do not restart the runtime: existing sessions keep the system prompt")
    lines.append("  they were created with; new SOUL/skills take effect from the next session. New on disk != new in the current session.")
    lines.append("  Open a new session to verify new-version behavior.")

    print("__REPORT_START__")
    print("\n".join(lines))
    print("__REPORT_END__")
    print(("DONE: version-info" if ok else "FAILED: index fetch error (local info above still valid)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
