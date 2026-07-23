---
name: portfolio-decision-engine
description: Policy-constrained Portfolio Manager (PM) decision workflow — compute investable/bucket weights, diagnose drifts and breaches, and emit three-layer recommendations with audit + chat rendering.
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  tags: [finance, portfolio, policy, decision-engine]
  sources:
    - docs/portfolio-policy.md
    - docs/pm-bot-decision-spec.md
---

# Overview
Use this skill whenever you need to transform Portfolio Truth + Policy into actionable, policy-consistent recommendations. It implements the four decision modes (Portfolio Review, Security Review, Rebalance, Exception/Override) and the three-layer output (portfolio/bucket/security) with audit trails and a concise chat renderer.

# When to Use
- User asks “What should I do with the portfolio now?”, “Rebalance?”, or similar.
- A daily/weekly/monthly decision summary needs to run.
- A single security crosses a band, or the user requests an action potentially outside policy.

# Prerequisites
- Portfolio Truth and Rules available (Truth, FX overrides, ringfence rules, MMF safety allocation).
- Policy thresholds defined (gold, cash, single-name caps, bands) — extend portfolio_rules.json if missing.
- Latest valuation snapshot (prices may be last-available, not RT).

# Inputs
- Portfolio Truth (holdings, qty, cost, ccy, sleeves), valuation snapshot, FX.
- Policy:
  - bucket_overrides: explicit bucket mapping by isin/ticker/name
  - gold_policy: {floor_hard, floor_pref, upper}
  - cash_policy: {min_investable, pref_low, pref_high}
  - single_name_caps: {normal_cap, exceptional_cap, core_target_min, core_target_max}
- User intent (mode selection, overrides, horizon if provided).

# Data Flow
1) Load portfolio truth + rules + FX → valuation snapshot.
2) Compute Safety/Obligation = ringfenced (PrivateFund/PrivateBiz) + min(120k USD, MMF). Investable = Total − Safety.
3) Classify positions into buckets (safety, cashflow, growth, hedge/insurance, tactical) via overrides → heuristics → fallback.
4) Compute bucket weights as % of Investable; compute gold% and investable cash%.
5) Diagnose portfolio stance and bucket statuses vs policy bands.
6) Generate three-layer recommendations per Decision Spec.
7) Render concise chat output; save full JSON for audit.

# Modes
- Portfolio Review: overall diagnosis and 3–5 actions.
- Security Review: one security with portfolio-context view and bands.
- Rebalance: when bands/thresholds breached or new capital arrives.
- Exception/Override: user asks outside policy — must present normal rec, why outside, risk, safer alternative, and smallest-risk implementation.

# Output (JSON)
- Layer 1 (Portfolio): overall_status, portfolio_stance[], primary_issue, next_best_use_of_capital, rebalance_required, override_warning_if_any.
- Layer 2 (Buckets): [{bucket_name, current_weight, target_band, status, recommended_action, rationale}].
- Layer 3 (Securities): top 3–5 items [{ticker, asset_type, current_weight, target_weight_or_range, action, priority, buy_band|trim_band zone, suggested_amount|quantity, rationale, key_risk, thesis_status, next_review_date}].

# Rendering (chat message)
- DEFAULT: Detailed English natural-language brief enumerating JSON fields in this fixed order (mirrors pm_engine.py render_detailed):
  1) Decision time; 2) Mode + policy version; 3) Valuation snapshot; 4) Overall status; 5) Portfolio stance; 6) Primary/secondary issue; 7) Next best use of capital; 8) Rebalance triggered; 9) Bucket/category diagnosis (current % / target band / status / action / rationale); 10) Specific securities & actions (action, amount/quantity, current weight, target range/buy-sell zone, rationale, key risk, thesis, next review); 11) Method note; 12) General risks.
- Do NOT emit the old concise summary unless the user explicitly requests it. Treat this format as locked unless the user asks to change it.
- Keep separate from the 18:00 SGT valuation push (FORMAT LOCKED). Never alter the price-push format.

# Auditability
- Save to ~/.hermes/portfolio/decisions/YYYYMMDD-HHMMSS_<mode>.json with: timestamp, mode, policy_version, snapshot_id, securities, payload, assumptions, override_flag, next_review_date.
- Also save a concise TXT next to the JSON for quick chat delivery.

# Scheduling
- Daily 18:05 SGT: concise decision dashboard.
- Weekly (Mon 18:10 SGT): stance + drift + key actions.
- Monthly (1st trading day 18:15 SGT): allocation vs target + rebalance candidates.
- Use Hermes cronjob tool with deliver=origin so summaries arrive in-chat. Do NOT interfere with the 18:00 SGT valuation push (keep this pipeline separate).

# Implementation Notes (Hermes tooling)
- read_file may prefix lines with "<lineno>|". Always strip these before json.loads when using tool outputs.
- read_file can return cache messages like "Old tool output cleared…" or "File unchanged since last read". For heavy processing or repeated reads, prefer direct Python I/O (open(...)) to avoid tool cache artifacts.
- When writing decisions programmatically, persist both JSON and a compact TXT summary.
- Keep bucket/policy logic in a reusable script (e.g., ~/.hermes/portfolio/pm_engine.py) for cron reuse.

# Default Bucket Overrides (examples)
- name::PrivateFund → safety; name::PrivateBiz → safety.
- MMF: allocate min(120k USD, MMF) to safety; remainder to tactical.
- name::Cash USD → tactical.
- ticker::IAU or names containing "Gold" → hedge.
- Demo Bond Fund/Demo SG Fund* fixed-income funds → cashflow.
- StructNote → growth (US) unless policy states otherwise.

# Steps (Implementation)
1. Extend portfolio_rules.json with bucket_overrides, gold_policy, cash_policy, single_name_caps (include Demo Bond Fund/Demo SG Fund→cashflow; MMF remainder→tactical; safety obligations; IAU→hedge).
2. Compute Safety and Investable; derive bucket weights, gold% and investable cash%.
3. Diagnose portfolio-level stance and bucket statuses; set rebalance_required triggers (gold<3%, cash<5%, single-name>10%, etc.).
4. Select top 3–5 securities based on gaps/concentration/opportunity; generate actions (hold/add/trim/exit/watch) with zone labels (avoid false precision).
5. Enforce non-negotiables: don’t use ringfenced capital; respect caps; avoid blind averaging down; block adds if cash below minimum unless justified.
6. Emit JSON (3 layers) and render the concise chat message; persist decision with audit fields.
7. Schedule daily/weekly/monthly decision summaries via cronjob, delivering concise text + MEDIA attachments of JSON/TXT.

# Verification
- Unit tests for bucket classification, Investable math, thresholds.
- Scenario checks: gold<3%, cash<5%, single-name>10%, growth>50%.
- Validate JSON schema fields present and values consistent.
- Manual review that the chat output stays within ~25 lines with 3–5 actions.

# Pitfalls
- Mixing push-format report with decisions — keep them separate; never change the LOCKED 18:00 SGT push format.
- False precision in buy/trim bands — prefer zones (staged accumulation/trim-on-strength).
- Hermes tool cache artifacts (lineno prefixes, cache messages) can corrupt JSON loads — strip prefixes or use direct file I/O.
- Ignoring policy conflict when a security looks attractive — policy takes precedence; use Override Mode when user insists.

# References
- docs/portfolio-policy.md
- docs/pm-bot-decision-spec.md
