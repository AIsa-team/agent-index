---
name: daily-stock-analysis
description: "AUTO-INVOKE for fast technical scans and market briefs. Triggers: scan TICKER (or 扫 TICKER, quick TICKER) for single/multi quick analysis; portfolio health (or portfolio-health, 持仓健康) for batch portfolio scan; market brief HK/US (or brief HK/US, 市场简报 HK/US) for index+sector overview. Output is a DSA-style 决策看板 / 市场简报 emitted on stdout for you to deliver."
---

> **Runtime bootstrap (dsa)** — this skill's scripts need a Python venv.
> Before first use (or if `${CLAUDE_PLUGIN_ROOT}/.venvs/dsa/bin/python` is missing), run:
> `bash "${CLAUDE_PLUGIN_ROOT}/scripts/ensure-venv.sh" dsa`
> Then invoke scripts with `${CLAUDE_PLUGIN_ROOT}/.venvs/dsa/bin/python`. First run installs dependencies and can take a few minutes.

> **Data bootstrap** — this skill reads files under the user data directory.
> If a path below does not exist yet, run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/ensure-data.sh"` first
> (idempotent: seeds missing files from the plugin's bundled assets, never overwrites existing data).
> - `~/.aisa/agents/aisa-cio/portfolio` — Portfolio data directory (portfolio_truth.json / engine scripts)(export `PORTFOLIO_DIR` to override — if set, use its value instead of this default)

> **Required credentials** — scripts resolve these as: env var → `~/.aisa/credentials` (KEY=VALUE lines):
> - `AISA_API_KEY` — AISA multi-model gateway — default LLM + aisa-* skills (search / marketpulse / prediction-markets / twitter). No key yet? Get one at https://console.aisa.one/get-started (takes about a minute).
> If a value is missing, do NOT fail silently and do NOT just tell the user to "export" it.
> Guide them through setup right here in the conversation:
> 1. If they don't have the key, give them the sign-up link above and wait.
> 2. Ask them to paste the key into the chat, then save it for them:
>    `mkdir -p ~/.aisa && printf 'NAME=value\n' >> ~/.aisa/credentials && chmod 600 ~/.aisa/credentials`
>    (replace NAME=value with the real pair; keep one KEY=VALUE per line).
> 3. Immediately retry the user's original command — the file takes effect at once, no host restart needed.
> If the user prefers not to paste secrets into chat, offer the alternative: they export the
> env var themselves in the host's environment, then restart the host. 不要静默失败 / never fail silently.

## MANDATORY ROUTING RULES

**These are hard rules with no exceptions.** When the user's message matches any of these patterns (case-insensitive), you MUST invoke this skill immediately using the `execute_code` tool.  Do NOT browse the web, do NOT analyze stocks yourself, do NOT use other skills — these scripts produce the full report themselves and print it between stdout markers for you to deliver.

| User's message pattern | Script to run | Notes |
|---|---|---|
| `scan TICKER [TICKER ...]`, `扫 TICKER`, `quick TICKER` | `dsa_scan.py TICKER ...` | 1–8 tickers; ~1–3 min each |
| `portfolio health`, `portfolio-health`, `持仓健康`, `持仓体检`, `健康扫描` | `dsa_port_health.py` | reads `portfolio_truth.json`, ~5–10 min total |
| `market brief HK`, `brief HK`, `市场简报 HK`, `港股简报` | `dsa_market_brief.py HK` | ~30 s |
| `market brief US`, `brief US`, `市场简报 US`, `美股简报` | `dsa_market_brief.py US` | ~30 s |

**OUTPUT RULE**: Every script prints `__REPORT_START__ ... __REPORT_END__` to stdout. The text between the markers IS the full DSA-style report (plus a trailing DONE:/FAILED: status line) — your job is to reply with that text verbatim so the user receives the report on your reply channel. Do NOT paraphrase, summarize, or add commentary.

## Trigger word disambiguation

- **Exact `portfolio`** → use the existing `portfolio-report` skill (live P&L). NOT this skill.
- **`portfolio health` / `持仓健康`** → THIS skill (`dsa_port_health.py`).
- **`ta TICKER` / `research TICKER` / `研究 TICKER`** → use the existing `trading-agents-research` skill (~5 min deep multi-agent analysis). NOT this skill.
- **`scan TICKER` / `quick TICKER`** → THIS skill (~1–3 min light technical scan).
- The two are complementary: use `scan` for daily monitoring, `ta` for high-conviction deep dives.

## How to invoke

### 1. Single or multi ticker quick scan

User says: `scan NVDA MSFT`

Run via `execute_code`:

```python
import subprocess, sys
result = subprocess.run(
    [
        "${CLAUDE_PLUGIN_ROOT}/.venvs/dsa/bin/python",
        "${CLAUDE_PLUGIN_ROOT}/skills/finance/daily-stock-analysis/scripts/dsa_scan.py",
        "NVDA", "MSFT",
    ],
    capture_output=True, text=True, timeout=900,
)
print(result.stdout)
sys.stderr.write(result.stderr)
```

### 2. Portfolio batch health scan

User says: `portfolio health`

```python
import subprocess, sys
result = subprocess.run(
    [
        "${CLAUDE_PLUGIN_ROOT}/.venvs/dsa/bin/python",
        "${CLAUDE_PLUGIN_ROOT}/skills/finance/daily-stock-analysis/scripts/dsa_port_health.py",
    ],
    capture_output=True, text=True, timeout=1800,
)
print(result.stdout)
sys.stderr.write(result.stderr)
```

### 3. Market brief

User says: `brief US`

```python
import subprocess, sys
result = subprocess.run(
    [
        "${CLAUDE_PLUGIN_ROOT}/.venvs/dsa/bin/python",
        "${CLAUDE_PLUGIN_ROOT}/skills/finance/daily-stock-analysis/scripts/dsa_market_brief.py",
        "US",
    ],
    capture_output=True, text=True, timeout=300,
)
print(result.stdout)
sys.stderr.write(result.stderr)
```

## Validation

Look at the tool result. It MUST contain `__REPORT_START__` and `__REPORT_END__` with non-empty body between them.

- If markers exist → reply ONLY with the text between markers, verbatim. That text is the full DSA-style report the user is waiting for.
- If markers are missing → reply ONLY: `ERROR: daily-stock-analysis script failed to produce output. Check stderr.` Do NOT fabricate analysis.

## Model routing

| Profile | Primary | Fallback | Used by |
|---|---|---|---|
| `fast_scan` | `deepseek-v4-pro` via AISA gateway (always reasons) | `gemini/gemini-2.5-flash` (thinking off) | `dsa_scan.py`, `dsa_port_health.py`, `dsa_market_brief.py` |

Configured inside `_dsa_lib.get_router()`. No environment overrides needed.

Routing decision (2026-04-30, user spec): T1/T2/T3 all use deepseek-v4-pro as
primary, gemini-2.5-flash as fallback. Quality first — DeepSeek-v4-pro provides
the strongest structured-output calibration and Chinese financial reasoning.
Gemini is a free-tier safety net (limited to 20 requests/day) for when the
AISA gateway (which serves the DeepSeek models) is unreachable.

## Resources

- Scripts:    `${CLAUDE_PLUGIN_ROOT}/skills/finance/daily-stock-analysis/scripts/`
- Shared lib: `_dsa_lib.py` (model routing, yfinance, formatting, report markers)
- Venv python: `${CLAUDE_PLUGIN_ROOT}/.venvs/dsa/bin/python` (managed by the platform's `setup.python` step)
- Holdings:   `~/.aisa/agents/aisa-cio/portfolio/portfolio_truth.json` (read-only)

## Hard guarantees

- Never modifies `portfolio_truth.json` or any portfolio data file.
- Uses the isolated venv behind `${CLAUDE_PLUGIN_ROOT}/.venvs/dsa/bin/python`; cannot affect Hermes's own Python environment.
- Falls back to DeepSeek if Gemini is unreachable.
- Does NOT include A-share coverage; tickers like `600519`/`000001` will return "no data" and be skipped.
