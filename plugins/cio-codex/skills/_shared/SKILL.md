---
name: _shared
description: "Shared python client library used by the aisa-* skills. Not a user-facing skill."
---

> **Required environment** — before running scripts, verify these variables are set (`echo $VAR`):
> - `AISA_API_KEY` — AISA multi-model gateway — default LLM + aisa-* skills (search / marketpulse / prediction-markets / twitter)
> If missing, STOP and tell the user to export it in the environment this plugin runs in
> (e.g. shell profile or the host app's env settings). 不要静默失败 / do not fail silently.

# _shared

Internal helper package (`aisa_client.py`). The `aisa-*` skills import it via
`${PLUGIN_ROOT}/skills/_shared`. Do not invoke directly.
