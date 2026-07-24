---
name: portfolio-update
description: "AUTO-INVOKE when user reports a portfolio change in natural language (我买了/卖了/加仓/减仓/清仓/新开仓/现金或MMF更新到/改成本价, bought/sold/trimmed/exited), or says 'port update'. Guides holdings updates via update_holdings.py — never hand-edit portfolio_truth.json."
---

> **Data bootstrap** — this skill reads files under the user data directory.
> If a path below does not exist yet, run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/ensure-data.sh"` first
> (idempotent: seeds missing files from the plugin's bundled assets, never overwrites existing data).
> - `~/.aisa/agents/aisa-cio/portfolio` — Portfolio data directory (portfolio_truth.json / engine scripts)(export `PORTFOLIO_DIR` to override — if set, use its value instead of this default)

# Portfolio Update — holdings-change guidance

Translate the user's natural-language holdings change into `update_holdings.py` commands: confirm before writing, auto-snapshot on write, verify afterward.

**Script**: `python3 ~/.aisa/agents/aisa-cio/portfolio/update_holdings.py`

| Command | Effect |
|---|---|
| `list` | List all holdings (index/name/ticker/qty/cost/ccy) |
| `buy TICKER QTY PRICE [--lot N]` | Add to position (weighted-average cost) |
| `sell TICKER QTY [--lot N]` | Trim position (cost unchanged; selling to 0 keeps the row and suggests remove) |
| `add TICKER QTY PRICE [--name NAME] [--ccy CCY]` | Add a new instrument (currency inferred from suffix: .HK→HKD, .T→JPY, .SI→SGD, default USD) |
| `remove TICKER [--lot N]` | Exit / delete the row (prints the full row before deleting) |
| `set TICKER cost\|qty AMOUNT [--lot N]` | Change cost/quantity |
| `set NAME value AMOUNT` | Cash/static-item valuation (Cash, MMF, MMF2, PrivateFund, PrivateBiz, StructNote) |

## Workflow (hard process, step by step)

1. **Parse** — extract action / ticker / qty / price from the user's message. If a parameter is missing, ask for it, one question at a time (e.g. "bought some NVDA" → ask quantity first, then fill price).
2. **Reconcile** — run `list` first (via terminal); never assume holdings from memory:
   - Instrument not in the list → use `add` (confirm full name and currency with the user);
   - Instrument in the list → use `buy`/`sell`/`set`;
   - Same ticker with multiple lots → show the lot list to the user and have them pick `--lot N`.
3. **Confirm** — restate the full change and wait for the user's explicit agreement, e.g.:
   "NVDA buy 100 sh @ USD 202.50 → position 100→200 sh, weighted-average cost ≈ 151.25. Execute?"
   **Never run any write command before the user explicitly agrees.**
4. **Execute** — run the corresponding command once, and forward the script output (including before/after and the `📸 snapshot:` line) to the user **verbatim**. The output must contain `✅` and `snapshot:`; if either is missing → treat it as a failure, show the raw error, do not retry, do not fabricate a result.
5. **Verify** — tell the user they can run `port` to see the updated live valuation. If execution failed or the user wants to undo: the latest snapshot is in `~/.aisa/agents/aisa-cio/portfolio/snapshots/`; rollback = copy the snapshot back to `portfolio_truth.json` (run `cp` only after user confirmation).

## `port update` guidance mode

When the user types `port update`: first run `list` to show current holdings, then ask "Which one do you want to change? (add / trim / new / exit / change cost / change cash)", and enter the same workflow above.

## Hard rules

- **Never hand-edit `portfolio_truth.json`** — all writes go through `update_holdings.py`.
- Quantities/prices/amounts must come from the user's own words or the user's confirmation — **never guess or auto-fill**.
- One conversation may handle multiple changes, but **confirm and execute one at a time**.
- After all changes are done, suggest the user run `port` to verify.
