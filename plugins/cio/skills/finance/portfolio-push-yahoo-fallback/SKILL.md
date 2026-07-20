---
name: portfolio-push-yahoo-fallback
title: Portfolio Push with Multi-Endpoint Yahoo Fallback
category: finance
description: Deterministic portfolio valuation and chat-friendly push using Yahoo multi-endpoint fallbacks (v7 quote → v8 chart → v7 spark), static valuation for MMF/StructNote/CODE items, at-cost valuation for HSBC 2028 bond, FX overrides, MMF safety allocation, ringfenced obligations, liabilities deduction, separate lots for duplicate tickers (e.g., 0700.HK A/B), JSON snapshotting, and cron scheduling at SGT 18:00 with manual /888 trigger.
tags: [portfolio, yahoo, valuation, cron, fx, fallback]
---

When to use
- Generate the user's portfolio push on schedule (SGT 18:00, Mon–Fri) or on-demand (/888).
- Yahoo realtime is unavailable or inconsistent — use last-available pricing with layered fallbacks.
- Apply portfolio-specific rules (FX overrides, MMF allocation, ringfencing, at-cost bond, duplicate-lot labeling) and output in the user's emoji/sectioned format.

Prerequisites
- Files (JSON):
  - Truth: ~/.hermes/portfolio/portfolio_truth.json
  - Rules: ~/.hermes/portfolio/portfolio_rules.json
- Strip line-number prefixes (e.g., "12|") from read_file outputs before JSON parsing.
- Rules must include:
  - fx_overrides: {HKDUSD, JPYUSD, SGDUSD, as_of}
  - mmf_safety_allocation_usd (e.g., 120000)
  - static_valuation (dict of CODE:* etc. → true)
  - mmf_codes (list of codes valued at 1)
  - liabilities: [{name, amount, ccy}]
- Optional: Finnhub key exists but is not required for this workflow; rely on Yahoo endpoints.

Pricing policy
1) Yahoo endpoints (layered):
   - v7 quote (query2 → query1) in batches (size ≈ 8).
   - For symbols missing price, call v8 chart (range=1mo, interval=1d) and take the most recent non-null close.
   - For any still missing, call v7 spark (range=1mo, interval=1d) and take the most recent non-null close.
   - Treat post/pre/previousClose as acceptable "last available" when regularMarketPrice is missing.
2) Static valuations:
   - Items with isin starting "CODE:", MMF codes, or StructNote → price = 1 [static].
   - Demo Bond 2028 → value at cost_per_unit [at cost].
3) FX: use Rules.fx_overrides only (no live FX). Convert HKD/JPY/SGD to USD.

Classification & labeling
- Sections (in order):
  - 🇺🇸 US Equities & ETFs (USD)
  - 🇭🇰 HK Equities (HKD)
  - 🇯🇵 Japan Equities (JPY)
  - 🇯🇵 Japan Funds (JPY)
  - 🏦 Fixed Income
  - 🇸🇬 Singapore Funds (SGD)
  - 💵 Cash & Private
- Heuristics:
  - CODE:* → Cash & Private.
  - StructNote → US Equities & ETFs.
  - *.HK → HK Equities; *.T → Japan Equities; Demo JP Fund → Japan Funds; Demo Bond Fund/Demo Bond 2028 → Fixed Income; Demo SG Fund → Singapore Funds; USD default → US Equities.
- Duplicate tickers (e.g., 0700.HK lots): label as "<ticker> (<name>)" so A/B display separately.

Computation
- Position value_usd = price × qty × FX(ccy→USD); cost_usd = cost_per_unit × qty × FX.
- PnL_usd = value_usd − cost_usd (when both available).
- Section subtotals and PnL = sum across positions.
- MMF allocation: allocate up to mmf_safety_allocation_usd from MMF totals to Safety; remaining MMF counts toward investable.
- Ringfence: add PrivateFund and PrivateBiz (full value) into Safety.
- Liabilities: convert via FX overrides and subtract from total.
- Net Portfolio Value (after liabilities) = Investable + Safety − Liabilities.

Output (chat-friendly) [FORMAT LOCKED — see references/format_template_locked.txt; do not modify without explicit user request]
- Three-line per holding layout (default):
  - Line 1: colored dot (🟢 gain, 🔴 loss, ⚪ flat) + *Name* (no ticker unless needed to disambiguate lots).
  - Line 2: "价格 {CCY} {price:0.0000} · {+/-0.00% day change if available, else +0.00%}".
  - Line 3: "持仓 {quantity} · 成本 {CCY} {unit_cost:0.0000}".
  - Line 4: "市值 ${value_int} · 盈亏 {dot} ${pnl_int} ({+/-x.x%})".
  - Quantity prints without trailing .00 when integer. Values print with thousand separators; 市值/盈亏 use integer dollars rounding; percentages round to 0.1%.
  - StructNote display rule: classify under US Equities; do NOT append [static] — show as a normal line with a colored dot.
  - Static/at-cost tags: keep [at cost] for Demo Bond 2028 when needed; omit [static] tags for cash/MMF/private to match the cleaner style.
- Section subtotals: one bold-ish line (plain text) at the end of each section:
  "*类别小计: $金额 · 🟢/🔴 +$盈亏 (+x.x%)*" (asterisks are literal, shown as-is in plain-text chat).
- Overall summary at the end:
  - 总市值
  - 整体盈亏（含百分比）
  - 扣除负债后净值（显示负债绝对额）
  - 资产类别分布：每类金额与占组合百分比（x.x%）。
- Headers and separators: use unicode lines like "━━━━━━━━━━━━━━━━━━━━" around section titles for readability.
- Preserve existing emoji section titles and ordering.

- No markdown; plain text with emoji headers.
- Header block:
  - FX summary with as_of
  - "MMF total → Safety … Remainder …"
  - "Safety ringfenced … | Investable …"
  - "Net Portfolio Value (after liabilities) …"
- For each section:
  - Header line with emoji (e.g., "🇺🇸 US Equities & ETFs (USD)")
  - "Subtotal: $ X  PnL: $ Y"
  - One line per holding: colored dot (🟢 gain, 🔴 loss, ⚪ none), label, "qty N.NN  value $ X", and "PnL $ Y (+/-Z%)" when applicable.
  - Append tags: "[static]" for price=1, "[at cost]" for HSBC bond.
- Do not surface internal source tags (v7 quote / v8 chart / v7 spark) — only [static]/[at cost].

Snapshotting
- Save JSON to ~/.hermes/portfolio/snapshots/<timestamp>_valuation_alt.json containing:
  - fx_overrides
  - positions [{sec,label,ccy,qty,price,note,value_usd,cost_usd,pnl_usd}]
  - section_subtotals, safety/investable, liabilities_total_usd, net_after_liabilities_usd
  - missing_quotes list
- In the chat, attach via: MEDIA:<snapshot_path>

Weekend behavior
- If day is Saturday/Sunday, send: "Non-trading day (weekend)" and skip full report.

Implementation sketch (Python with hermes_tools)
1) Read Truth/Rules (strip line numbers).
2) Build symbols list excluding CODE:*.
3) Fetch quotes in this order:
   - v7 quote (query2 → query1), batch size 8.
   - For any missing, v8 chart last non-null.
   - For any still missing, v7 spark last non-null.
4) Apply pricing rules, compute USD values and PnL.
5) Allocate MMF to Safety, ringfence PrivateFund/PrivateBiz, subtract liabilities.
6) Format text and save snapshot; print formatted text then MEDIA:<snapshot>.

Pitfalls & tips
- Yahoo rate limits/region blocks: keep batch size small (≈8), retry on query2→query1, and rely on chart/spark fallbacks.
- Some funds (0P000… symbols) rarely have realtime in v7; chart/spark last close is typically available.
- Ensure duplicate-lot labeling so 0700.HK A/B lines are visible.
- Always include FX as_of in header; no live FX.
- When using read_file outputs with line numbers, always strip prefixes before json.loads.

Verification checklist
- Section subtotals sum equals the sum of constituent positions.
- 0700.HK lots appear as two lines with distinct labels.
- Demo Bond 2028 shows "[at cost]" and zero PnL.
- Safety includes PrivateFund, PrivateBiz, and up to 120k from MMF; Investable includes MMF remainder and Cash USD.
- Net after liabilities equals Safety + Investable − Liabilities.

Scheduling
- Use cronjob(action='create', schedule='0 10 * * 1-5') to run daily at 18:00 SGT (UTC+8). Deliver to current chat and attach snapshot.
