---
name: trading-agents-research
description: "AUTO-INVOKE when user says ta [ticker], research [ticker], or 研究 [ticker]. Runs the real TradingAgents multi-agent framework (analysts + debate + risk + PM) for a single stock ticker."
references:
  - scripts/call_trading_agents.py
---

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

### Trading Agents Single Ticker Deep Research

Calls the **real** TradingAgents multi-agent framework. Runtime ≈ 15-20 minutes.

The script runs in the **background** and caches the finished report on disk
(`~/.tradingagents/results/<TICKER>/<date>-report.txt`). Your jobs are to
(1) confirm the research started, (2) retrieve the cached report with
`--resend` when the user asks for the result (or after ~20 minutes), and
(3) handle any error status.

---

#### HOW TO LAUNCH RESEARCH

**Step 1** — Extract the ticker from the user's message (uppercase, strip whitespace). Tell the user:
`Starting TradingAgents research for <TICKER>. This takes 15-20 minutes — ask me for the result later (e.g. "resend <TICKER>") and I will fetch the finished report.`

**Step 2** — Call `execute_code` ONCE with `timeout=60`. Replace `<TICKER>` with the uppercase ticker string (e.g. `"NVDA"`):

```python
import os, importlib.util, sys

script_path = os.path.expanduser("${PLUGIN_ROOT}/skills/trading-agents-research/scripts/call_trading_agents.py")
spec = importlib.util.spec_from_file_location("call_ta_module", script_path)
mod = importlib.util.module_from_spec(spec)
sys.modules["call_ta_module"] = mod
spec.loader.exec_module(mod)

status = mod.run_in_background(<TICKER>)
print(status)
```

**Step 3 — MANDATORY STATUS VALIDATION:**

The output MUST start with exactly one of: `STARTED:`, `DONE:`, or `FAILED:`.

- `STARTED:` → relay to user verbatim. Research is running in background; the report is retrievable later (see below). **No further action needed now.**
- `DONE:` → the full report follows the status line — deliver it (see delivery rules below).
- `FAILED:` → relay verbatim so user sees the error. **Do NOT retry automatically.**
- Empty or none of the above → reply ONLY with: `ERROR: TradingAgents failed to start (status-line validation did not pass).`

---

#### HOW TO RETRIEVE THE FINISHED REPORT

When the user asks for the result (**"resend [ticker]"** / **"重新发送 [ticker]"** / "研究结果好了吗"), fetch it from cache without re-running TA:

```python
import os, importlib.util, sys

script_path = os.path.expanduser("${PLUGIN_ROOT}/skills/trading-agents-research/scripts/call_trading_agents.py")
spec = importlib.util.spec_from_file_location("call_ta_module", script_path)
mod = importlib.util.module_from_spec(spec)
sys.modules["call_ta_module"] = mod
spec.loader.exec_module(mod)

status = mod.run_and_report(<TICKER>, resend=True)
print(status)
```

Use `execute_code` with `timeout=120` for this call (it only reads cache, no TA run).

- `DONE:` → the full report follows. Deliver sections **1. FINAL DECISION** and **2. TRADING PLAN** verbatim; then offer the remaining sections (debate, risk, analyst reports) on request or deliver them in follow-up messages. Do not rewrite or summarise the decision/plan content itself.
- `FAILED: No cached result found` → research is still running (or was never started). Tell the user to wait, or launch a fresh run if none was started today.

---

#### Parameters
- `ticker`: Stock ticker symbol (e.g., `"NVDA"`, `"AAPL"`, `"AMD"`)

#### Rules
- Call `run_in_background` **exactly ONCE** per research request — never loop or retry.
- The result IS cached on disk after every successful run. Use **resend** to retrieve it — never a fresh run just to re-read a report.
- If you get `FAILED:`, report the error to the user and stop. Do not retry automatically.
- **Never** compose research content from memory — 100% of user-facing research comes from the report text printed by the script.
