---
name: portfolio-report
description: "AUTO-INVOKE when user says 'port' (exactly). Runs the live portfolio report script and returns output verbatim."
---

> **Required environment** — before running scripts, verify these variables are set (`echo $VAR`):
> - `PORTFOLIO_DIR` — required by this skill
> If missing, STOP and tell the user to export it in the environment this plugin runs in
> (e.g. shell profile or the host app's env settings). 不要静默失败 / do not fail silently.

## MANDATORY ROUTING RULE
**This is a hard rule with no exceptions.** When the user's message is exactly `port` (case-insensitive, may have leading/trailing spaces, no other words):

1. **You MUST invoke this skill immediately** using the skills tool (`skill_view` then execute it). Do NOT describe the portfolio from memory. Do NOT use `delegate_task`. The skill runs the live portfolio script with real-time prices.

2. **OUTPUT RULE**: The script produces a pre-formatted report. Your response MUST be the exact text between `__REPORT_START__` and `__REPORT_END__` markers — copy it character-for-character. Do NOT add any intro, summary, or commentary.

### Live Portfolio Report

Generates a live portfolio snapshot with real-time prices and FX rates. Runtime ≈ 30 seconds.

#### HOW TO USE:

**Step 1** — Tell the user: `Fetching live portfolio data...`

**Step 2** — Call the `execute_code` tool ONCE. The `code` argument MUST be exactly the following Python (do NOT wrap it in another `print(...)` call, do NOT wrap it in extra quotes, pass the code body directly):

```python
import subprocess, sys
result = subprocess.run(
    [sys.executable, "${PORTFOLIO_DIR}/portfolio_report.py"],
    capture_output=True, text=True, timeout=300
)
if result.returncode != 0:
    print("__REPORT_START__")
    print("ERROR: " + (result.stderr or "exit " + str(result.returncode))[-500:])
    print("__REPORT_END__")
else:
    print("__REPORT_START__")
    print(result.stdout.strip())
    print("__REPORT_END__")
```

**Step 3 — MANDATORY OUTPUT VALIDATION (before you reply to the user):**
Look at the tool result. It MUST satisfy ALL of:
1. Contains the literal string `__REPORT_START__`
2. Contains the literal string `__REPORT_END__`
3. The text BETWEEN those two markers contains the line `__DATA_SOURCE__:` (emitted by the real script)
4. The text between markers is NOT empty

**IMPORTANT: Portfolio Truth Verification**
The authoritative set of holdings is whatever is defined in `${PORTFOLIO_DIR}/portfolio_truth.json`. Do NOT assume any specific tickers — the script reads that file and prices it live. The presence of the `__DATA_SOURCE__:` line (emitted only by the real script) is the canonical proof that the output came from the configured truth file and not from memory or fabrication.

If the report is missing the `__DATA_SOURCE__:` line, OR it lists holdings that do not appear in `${PORTFOLIO_DIR}/portfolio_truth.json`, treat the data as fabricated and reject it.

If ANY check fails → reply ONLY with:
`ERROR: 持仓报告执行失败（数据源校验未通过），请检查 portfolio_report.py 日志。`
Do NOT fabricate data. Do NOT retry. Do NOT summarise. Stop.

If ALL checks pass → reply with the EXACT text between `__REPORT_START__` and `__REPORT_END__`, verbatim, character-for-character. No preamble, no summary, no closing remark.

#### Rules:
- Run the script **exactly ONCE** per `port` request.
- Your only jobs are: (a) call the tool correctly, (b) validate the output, (c) relay or error.
- You are FORBIDDEN from composing portfolio content from memory, training data, or prior conversation — 100% of the numbers and tickers must come from the tool output between the markers.