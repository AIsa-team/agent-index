---
name: monthly-allocation-review
description: Monthly portfolio allocation review — load rules + latest valuation, compute bucket weights vs targets, identify rebalance candidates, enforce gold/cash/single-name caps, save JSON+TXT, and deliver a concise summary.
version: 1.0.0
author: Hermes Agent
metadata:
  tags: [finance, portfolio, review, monthly]
  sources:
    - ~/.hermes/portfolio/monthly_review.py
---

# When to Use
Scheduled cron: 1st trading day of each month at 18:15 SGT (or on demand).

# Steps
1. Load portfolio_rules.json and portfolio_truth.json from ~/.hermes/portfolio/.
2. Run valuation_push.py to get fresh live prices.
3. Extract live values from the valuation output into the script's values_usd dict.
4. Compute:
   - Safety (ringfenced PrivateFund + PrivateBiz + MMF_alloc)
   - Investable = Gross - Safety - Liabilities
   - Bucket weights: cashflow, hedge (gold/IAU), tactical (cash+MMF remainder), growth
   - Gold% of investable (policy: floor 3%, pref 5%, upper 8%)
   - Cash% of investable (policy: min 5%, pref 8-12%)
   - Single-name concentrations (for MMF, count only tactical portion)
5. Diagnose breaches: gold hard/pref floor, cash minimum, single-name caps, bucket drifts.
6. Generate 5 priority-ordered recommendations:
   (1) Gold policy action, (2) Cash allocation action, (3) Cashflow/structural action,
   (4) Regional/thematic review, (5) Checklist completion.
7. Save JSON (full payload) and TXT (rendered output) to ~/.hermes/portfolio/decisions/.
8. Deliver concise summary as final response with MEDIA attachments of both files.

# Key Logic
- MMF is split: min(MMF_total, 120k) → Safety, remainder → Tactical
- Single-name caps for MMF use only the tactical/investable portion
- Cashflow bucket: Demo Bond Funds, Demo SG Fund funds, Demo Bond 2028 (per bucket_overrides in rules)
- Gold = iShares Gold / IAU only

# Pitfalls
- Always update values_usd dict with fresh valuation output before running
- Ensure rec #2 does not reference need_pref (defined only in gold branch) — use inline formula
- The script is at ~/.hermes/portfolio/monthly_review.py — rerun after truth/rules changes
- Check that FX overrides are current; stale FX can misstate HKD/JPY/SGD positions
