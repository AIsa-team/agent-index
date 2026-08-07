---
name: trading-agents-research
description: "AUTO-INVOKE on the command forms `research TICKER` / `研究 TICKER` (quick tier, ~1 min), `deep-research TICKER` / `深度研究 TICKER` (deep tier, ~3 min) and `full-report TICKER` / `全量报告 TICKER` (full tier, ~9 min) — a trigger word plus a ticker symbol. Quick is a single-model quick take; deep and full run the real TradingAgents multi-agent framework. Legacy triggers `ta` / `deep` / `fast-research` / `快研` are RETIRED — on seeing them, use the command-specific replacement guidance below instead of running. NOT for free-form 'deep research' prose without a ticker — that is `multi-source-search`'s job."
---

> **Required credentials** — scripts resolve these as: env var → `~/.aisa/credentials` (KEY=VALUE lines):
> - `AISA_API_KEY` — AISA multi-model gateway — default LLM + the agent-skills data skills (marketpulse / multi-source-search / prediction-market-data / aisa-twitter-api / last30days). No key yet? Get one at https://console.aisa.one/get-started (takes about a minute).
> If a value is missing, do NOT fail silently and do NOT just tell the user to "export" it.
> Guide them through setup right here in the conversation:
> 1. If they don't have the key, give them the sign-up link above and wait.
> 2. Ask them to paste the key into the chat, then save it for them:
>    `mkdir -p ~/.aisa && printf 'NAME=value\n' >> ~/.aisa/credentials && chmod 600 ~/.aisa/credentials`
>    (replace NAME=value with the real pair; keep one KEY=VALUE per line).
> 3. Immediately retry the user's original command — the file takes effect at once, no host restart needed.
> If the user prefers not to paste secrets into chat, offer the alternative: they export the
> env var themselves in the host's environment, then restart the host. 不要静默失败 / never fail silently.

### Three-Tier Single Ticker Research

One skill, three tiers. Pick the tier from the trigger word — never guess a
deeper tier than the user asked for:

| Tier | Triggers | Pipeline | Runtime | Interaction |
|---|---|---|---|---|
| **quick** | `research [ticker]`, `研究 [ticker]` | NO multi-agent: price/technicals/fundamentals pull + ONE flash LLM call | < 1 min | **synchronous** — result comes back in the same call |
| **deep** | `deep-research [ticker]`, `深度研究 [ticker]` | real TradingAgents: market + fundamentals analysts + debate + risk + PM; all-flash models | ~3 min | background + resend |
| **full** | `full-report [ticker]`, `全量报告 [ticker]`, `完整报告 [ticker]` | real TradingAgents: all 4 analysts (market/sentiment/news/fundamentals) + debate + risk + PM; hybrid pro+flash | ~9 min | background + resend |

**Retired triggers**: `ta`, `deep`, `research`-as-full, `fast-research`, `快研`.
If the user types one of these, do NOT launch anything. Reply with the
closest command-specific replacement:

- `fast-research T` / `快研 T` → `deep-research T` (same intent: reduced multi-agent research, ~3 min).
- `ta T` / `deep T` → ask whether they want `deep-research T` (~3 min) or `full-report T` (~9 min complete investment research report); if they clearly want the old complete TA run, point to `full-report T`.
- `research`-as-full → `full-report T`; plain `research T` is now quick only.

Neither quick nor deep consults news/sentiment. For that coverage use
`marketpulse`/`multi-source-search` for news and `last30days`/`aisa-twitter-api`
for social sentiment — or `full-report`, which includes both analysts.
`scan [ticker]` is technical-only and must not be described as news or
sentiment coverage.

Deep and full runs execute in the **background** and cache the finished report
on disk (`~/.tradingagents/results/<TICKER>/<date>-deep-report.txt` for deep,
`<date>-report.txt` for full). Quick runs synchronously and prints its report
immediately (also cached, `<date>-quick-report.txt`).

---

#### TIER 1 — QUICK (`research TICKER`)

Run ONE `execute_code` call with `timeout=120`. Replace `<TICKER>` with the
uppercase ticker string (e.g. `"NVDA"`):

```python
import os, importlib.util, sys

script_path = os.path.expanduser("${CLAUDE_PLUGIN_ROOT}/skills/trading-agents-research/scripts/call_trading_agents.py")
spec = importlib.util.spec_from_file_location("call_ta_module", script_path)
mod = importlib.util.module_from_spec(spec)
sys.modules["call_ta_module"] = mod
spec.loader.exec_module(mod)

status = mod.run_quick_research(<TICKER>)
print(status)
```

- `DONE:` → the quick report follows; deliver it **verbatim** (it already
  carries the `[QUICK MODE …]` header and the full-report tip — both MUST
  reach the user).
- `FAILED:` → relay verbatim. Do NOT retry automatically, and NEVER compose a
  quick take yourself from memory — no data, no take.

No background process, no resend dance, no ETA message needed.

---

#### TIER 2 & 3 — DEEP / FULL (background launch)

**Step 1** — Extract the ticker (uppercase, strip whitespace) and set
`<MODE>` from the trigger: `deep-research`/`深度研究` → `"deep"`,
`full-report`/`全量报告` → `"full"`. Tell the user:
`Starting <mode> research for <TICKER>. This takes ~3 minutes (deep) / ~9 minutes (full) — ask me for the result later (e.g. "resend <TICKER>") and I will fetch the finished report.`

**Step 2** — Call `execute_code` ONCE with `timeout=60`:

```python
import os, importlib.util, sys

script_path = os.path.expanduser("${CLAUDE_PLUGIN_ROOT}/skills/trading-agents-research/scripts/call_trading_agents.py")
spec = importlib.util.spec_from_file_location("call_ta_module", script_path)
mod = importlib.util.module_from_spec(spec)
sys.modules["call_ta_module"] = mod
spec.loader.exec_module(mod)

status = mod.run_in_background(<TICKER>, mode=<MODE>)
print(status)
```

**Step 3 — MANDATORY STATUS VALIDATION:**

The output MUST start with exactly one of: `STARTED:`, `DONE:`, or `FAILED:`.

- `STARTED:` → relay to user verbatim. Research is running in background; the report is retrievable later (see below). **No further action needed now.**
- `FAILED:` → relay verbatim so user sees the error. **Do NOT retry automatically.**
- Empty or none of the above → reply ONLY with: `ERROR: TradingAgents failed to start (status-line validation did not pass).`

---

#### HOW TO RETRIEVE A FINISHED DEEP/FULL REPORT

When the user asks for the result (**"resend [ticker]"** / **"重新发送 [ticker]"** / "研究结果好了吗"), fetch it from cache without re-running. Use the **same mode** as the launch (each tier has its own cache; a FAILED line will tell you if today's result exists in another tier):

```python
import os, importlib.util, sys

script_path = os.path.expanduser("${CLAUDE_PLUGIN_ROOT}/skills/trading-agents-research/scripts/call_trading_agents.py")
spec = importlib.util.spec_from_file_location("call_ta_module", script_path)
mod = importlib.util.module_from_spec(spec)
sys.modules["call_ta_module"] = mod
spec.loader.exec_module(mod)

status = mod.run_and_report(<TICKER>, resend=True, mode=<MODE>)
print(status)
```

Use `execute_code` with `timeout=120` for this call (it only reads cache, no research run).

- `DONE:` + **deep mode** → the Research Brief follows (investment view, key
  evidence, key risks, action plan, what to watch next, and the full-report
  tip). Deliver it verbatim — do not rewrite or summarise. The
  complete deep output (debate, risk, analyst reports) is already on disk; if
  the user asks for it, call `run_and_report(<TICKER>, resend=True,
  mode="deep", full_text=True)`.
- `DONE:` + **full mode** → the Full Investment Research Report follows
  (executive brief, investment view, evidence, bull/bear/neutral view, risks,
  trading and portfolio action plan, analyst summaries, what to watch next, and
  no standalone source section). Deliver it verbatim — do not rewrite,
  summarise, or split it into "remaining sections." The raw TradingAgents
  sections are retained only as an internal fallback if report synthesis fails.
- `FAILED: No cached ... result found` → research is still running (or was
  never started, or was launched in another tier — the message names any tier
  that DOES have today's result). Tell the user to wait, or launch a fresh run
  if none was started today.

#### Parameters
- `ticker`: Stock ticker symbol (e.g., `"NVDA"`, `"AAPL"`, `"AMD"`)
- `mode`: `"quick"`, `"deep"` or `"full"` (`"fast"` is accepted as a legacy alias for `"deep"`)

#### Rules
- **Command forms only.** Auto-invoke on `research TICKER` / `deep-research TICKER` / `full-report TICKER` / `研究 TICKER` / `深度研究 TICKER` / `全量报告 TICKER` — a trigger word followed by a ticker symbol. Do NOT auto-invoke on free-form prose that merely contains the word "research" ("do a deep dive on the chip cycle", "deep research on tariffs") — that is narrative research and belongs to `multi-source-search`. If the intent is ambiguous, ask which the user wants instead of burning a multi-minute run.
- **Never escalate tiers on your own.** `research` runs quick — do not launch deep/full because you think the user "really wants" more depth. Mention the deeper tiers (the report footer already does) and let the user decide.
- Call `run_in_background` **exactly ONCE** per research request — never loop or retry.
- The result IS cached on disk after every successful run. Use **resend** to retrieve it — never a fresh run just to re-read a report.
- The three tiers' caches are separate; a deep run never overwrites a full report (and vice versa).
- If you get `FAILED:`, report the error to the user and stop. Do not retry automatically.
- **Never** compose research content from memory — 100% of user-facing research comes from the report text printed by the script.
- **Never** present a quick or deep report as full research — the `[QUICK MODE …]` / `[DEEP RESEARCH …]` headers and the full-report tip must reach the user.
