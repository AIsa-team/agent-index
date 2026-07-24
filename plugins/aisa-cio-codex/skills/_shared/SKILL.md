---
name: _shared
description: "Shared python client library used by the aisa-* skills. Not a user-facing skill."
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

# _shared

Internal helper package (`aisa_client.py`). The `aisa-*` skills import it via
`${PLUGIN_ROOT}/skills/_shared`. Do not invoke directly.
