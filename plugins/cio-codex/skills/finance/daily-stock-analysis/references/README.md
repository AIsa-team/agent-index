# daily-stock-analysis — Reference notes

## Triggers (cheat sheet)

| What user types | What runs | Time | Output |
|---|---|---|---|
| `scan NVDA` | `dsa_scan.py NVDA` | ~1–2 min | DSA decision dashboard for NVDA → stdout markers |
| `scan NVDA MSFT 0700.HK` | `dsa_scan.py NVDA MSFT 0700.HK` | ~3–6 min | one dashboard per ticker → stdout markers |
| `port health` | `dsa_port_health.py` | ~5–10 min | summary table + bearish detail dashboards → stdout markers |
| `brief US` | `dsa_market_brief.py US` | ~30 s | indices + sector rotation summary → stdout markers |
| `brief HK` | `dsa_market_brief.py HK` | ~30 s | HSI + HSCEI + HSTECH brief → stdout markers |

The Hermes agent replies with the marker body verbatim, so the report reaches
the user on whatever channel the gateway serves.

## Data flow

```
yfinance (OHLCV)
   ↓
_dsa_lib.fetch_snapshot()       → MA / RSI / MACD / volume / 52w stats
   ↓
_dsa_lib.call_llm_dashboard()   → LiteLLM Router
                                    primary:  deepseek-v4-pro via AISA gateway (always reasons)
                                    fallback: gemini/gemini-2.5-flash (thinking off)
   ↓
_dsa_lib.format_dashboard()     → Markdown decision dashboard
   ↓
__REPORT_START__ <full report> + DONE: ... __REPORT_END__
                                → stdout for Hermes skill consumption;
                                  the agent delivers it on its reply channel
```

## Files NOT touched (guarantees)

- `${PORTFOLIO_DIR}/portfolio_truth.json` — read-only access
- `${PORTFOLIO_DIR}/portfolio_rules.json` — never read
- All other `portfolio-*` skills under `${PLUGIN_ROOT}/skills/finance/`
- `~/.hermes/config.yaml`, `~/.hermes/secrets/*.key`, `~/.hermes/channel_directory.json` — read-only
- ubuntu user crontab (the 18:00 SGT portfolio_cron job is preserved as-is)

## Testing from the shell

```bash
${PLUGIN_ROOT}/.venvs/dsa/bin/python \
    ${PLUGIN_ROOT}/skills/finance/daily-stock-analysis/scripts/dsa_scan.py \
    NVDA
```

Progress logs print to stderr; the full report goes to stdout between
`__REPORT_START__/__REPORT_END__` markers.

## Model strategy

Quality-first routing (2026-04-30, user spec). T1/T2/T3 share the same chain:

| Tier | Profile | Primary | Fallback |
|---|---|---|---|
| 1 — fast | `fast_scan` | `deepseek-v4-pro` via AISA gateway (always reasons) | `gemini/gemini-2.5-flash` (thinking off) |
| 2 — deep | `deep_research` | `deepseek-v4-pro` via AISA gateway (always reasons) | `gemini/gemini-2.5-flash` (thinking medium) |

The `trading-agents-research` skill (separate) follows the same chain via its own
`PROVIDER_CHAIN = ("deepseek", "gemini")`.

Why DeepSeek-v4-pro as primary: best calibration of structured signals, native
Chinese financial vocabulary, and consistent always-on reasoning. Gemini-2.5-flash
is the safety net (limited free tier — 20 RPD); upgrade Google billing for
serious fallback usage.

## Removed / not implemented (per user requirements)

- ❌ A-share coverage (no AKShare/Tushare/efinance)
- ❌ Daily cron schedule (manual trigger only, observation period first)
- ❌ Web UI / FastAPI server
- ❌ Backtesting module
- ❌ Direct chat-platform push (reports go through Hermes's reply channel only)
