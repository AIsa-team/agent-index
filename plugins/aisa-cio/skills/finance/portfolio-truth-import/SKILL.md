---
name: Portfolio Truth — Import and Normalization
description: Robust workflow to ingest messy portfolio inputs (markdown/tables with line-break glitches) into portfolio_truth.json and portfolio_rules.json, with snapshots, symbol_map and needs_isin scaffolding.
version: 1.0
created: 2026-04-14
owner: Hermes
summary: Initialize and normalize portfolio data from semi-structured sources; handle HK broken rows, post-fill tickers, controlled CODE classes, rules writing, and snapshotting.
---

When to use
- You receive a portfolio in semi-structured markdown with mixed asset classes and currencies.
- HK tables are misformatted (tickers on their own lines, repeated), and some funds show Yahoo tickers on subsequent lines.
- You need to initialize or refresh ~/.hermes/portfolio/ files with snapshots and mapping scaffolds.

Prerequisites
- Paths: ~/.hermes/portfolio/portfolio_truth.json, portfolio_rules.json, snapshots/.
- Respect user conventions:
  - Cash/private/static classes must use controlled ISIN codes (CODE: prefix).
  - FX overrides are authoritative and dated (as_of).
  - 0700.HK two lots kept separate.
  - MMF USD: first $120k to safety obligation; remainder investable cash.
  - StructNote bucketed as US_EQUITY with static valuation.
  - JP Margin Loan is a liability deducted from net.
- Finnhub API key for ISIN mapping (optional initial step; mapping is "pending" if missing).

Workflow (numbered)
1) Sectioning
   - Split input by section headers beginning with "## ". Identify at least: FX, US Equities, HK Equities, Japan Equities, Japan Funds, Fixed Income, Singapore Funds, Cash & Private.
2) Utilities
   - Implement clean_number to parse comma-separated numerics.
3) FX overrides
   - Extract pairs like "- HKD/USD = 0.1285" into {"HKDUSD": 0.1285, ...}, and record as_of date from input.
4) US Equities (well-formed table)
   - Parse markdown table rows (skip header/divider). Capture: name, yahoo_ticker (or fallback to ticker), qty, cost_per_unit, cost_ccy=USD.
5) HK Equities (misformatted)
   - Scan lines for pattern NNNN.HK. The next line with a pipe-delimited row holds Name | Qty | Cost.
   - Create items with yahoo_ticker=ticker, cost_ccy=HKD. Keep duplicate tickers as separate lots (e.g., 0700.HK A/B remain two items).
6) Japan Equities (table)
   - Parse like US; cost_ccy=JPY.
7) JP Margin Loan
   - Extract e.g., "JP Margin Loan: ¥22,387,929" as liabilities entry.
8) Japan Funds
   - Parse table including ISIN; cost_ccy=JPY.
9) Fixed Income (broken ticker lines)
   - Parse table rows; if Yahoo Ticker cell is empty or "N/A (OTC)", scan the following non-table lines until the next row for a token like 0P000... or TICKER.SUFFIX and fill it.
   - Keep ISIN when present.
10) Singapore Funds (broken ticker lines)
   - Parse table; collect ticker-like tokens in the block and post-fill missing Yahoo tickers in order.
11) Cash & Private (controlled codes)
   - Map names to codes with tags:
     - Cash USD → CODE:CASH-USD (tags: [cash])
     - StructNote → CODE:STRUCTNOTE (tags: []; static valuation true; classification override US_EQUITY)
     - MMF USD → CODE:MMF-USD (tags: [mmf])
     - MMF2 → CODE:MMF2 (tags: [mmf])
     - PrivateFund → CODE:PRIVATEFUND (tags: [private, safety])
     - PrivateBiz → CODE:PRIVATEBIZ (tags: [private, safety])
   - Represent these as items with qty=value and cost_per_unit=1.
12) Compose Truth
   - Concatenate all items into an array with fields: isin, name, yahoo_ticker, qty, cost_per_unit, cost_ccy, meta.
13) Write files and snapshots
   - Write portfolio_truth.json and portfolio_rules.json. Then snapshot to snapshots/<timestamp>_portfolio_truth.json and snapshots/<timestamp>_portfolio_rules.json.
14) Create mapping scaffolds
   - From items with isin==null (exclude CODE:), build symbol_map.json keyed by yahoo_ticker with {isin:null, source:"pending", name, cost_ccy}.
   - Persist needs_isin.json listing items needing mapping (counts should be ~items with null ISIN; duplicate tickers may reduce symbol_map key count).
15) ISIN mapping (when Finnhub key is available)
   - For each pending symbol, query Finnhub by symbol/venue or by name+exchange; prefer exact ISIN. Record in symbol_map.json and backfill portfolio_truth.json if appropriate (after confirmation).

Verification
- Category counts match input: e.g., US 6, HK 7 (incl. 0700.HK A/B), JP equities 4, JP funds 1, Fixed Income 4, SG funds 2, Cash/Private 6; total ~30.
- needs_isin count reflects null-ISIN items (e.g., 17), while symbol_map may have fewer keys due to shared ticker across lots (e.g., 16 keys with 0700.HK shared).
- Snapshots exist with the current timestamp, and files are parseable JSON (no line-number prefixes).

Pitfalls and fixes
- read_file returns line-number-prefixed output (e.g., " 12| {") — strip the prefix before json.loads. Prefer direct Python file IO when inside execute_code to avoid prefixes.
- HK section often has repeated ticker lines and empty table scaffolding; anchor on ticker regex NNNN.HK and then find the next pipe-row.
- Fixed Income and Singapore funds often spill Yahoo tickers onto the next line — implement a lookahead to capture tokens like 0P000... or TICKER.SUFFIX.
- Ensure 0700.HK two lots are kept separate and both point to the same yahoo_ticker with distinct qty/cost.
- Never invent ISINs; if Finnhub lookup fails, leave as pending and report transparently.
- MMF safety allocation rule (first $120k) is applied at report time, not baked into Truth entries.

Example tool snippets
- Strip line-number prefixes:
  for line in raw.splitlines():
      lines.append(line.split('|',1)[1] if '|' in line else line)
  text='\n'.join(lines)
  data=json.loads(text)

- Snapshot naming: use `date +%Y%m%d-%H%M%S`.

Outcome
- Clean portfolio_truth.json and portfolio_rules.json with snapshots.
- symbol_map.json and needs_isin.json ready for ISIN mapping and pricing workflows.
