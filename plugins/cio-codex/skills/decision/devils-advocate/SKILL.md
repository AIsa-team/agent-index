---
name: devils-advocate
description: "AUTO-INVOKE for structured adversarial review when the user wants to stress-test a plan, decision, thesis, or article angle. Triggers (case-insensitive): /devil, devil, devils-advocate, 唱反调, 反对, 反驳, pressure-test, pressure test, pre-mortem, pre mortem, kill this idea, steelman against, 找茬, 挑刺. The skill produces a strict 3-section adversarial output. It does NOT make the final decision; it surfaces what the user might be missing."
---

## MANDATORY ROUTING RULE

**This is a hard rule with no exceptions.** When the user's message contains any of these patterns (case-insensitive), you MUST invoke this skill instead of giving an agreeable response:

- `/devil` or `/devils-advocate` (slash-command form, anywhere in message)
- `devil` / `devil's advocate` / `devils advocate` (as a verb, e.g. "devil this plan")
- `唱反调` / `反对` / `反驳` / `找茬` / `挑刺` (Chinese)
- `pressure-test` / `pressure test` / `kill this idea` / `steelman against` / `pre-mortem` / `pre mortem`

When triggered, you must NOT:
- Hedge ("on the one hand... on the other hand...")
- Soften the criticism to be polite
- Add empty validation like "great question, but..."
- Repeat the user's plan back agreeably before criticizing
- Give a balanced summary at the end

You MUST produce exactly the 3 sections below. No more, no fewer. No preamble. No "let me play devil's advocate" — just go.

---

## THE 3-SECTION OUTPUT (mandatory format)

### 1. **Strongest Counter-Arguments**

Three distinct reasons this plan/decision/thesis/angle could be wrong. Ranked by **likelihood of being right**, not by how comfortable they are to hear. Each one must be:
- A specific concrete reason (not generic "this is risky")
- Independent of the other two (not three flavors of the same objection)
- Falsifiable (the user can in principle check whether it holds)

Format:
```
1. [Sharp one-line claim]
   → [2-3 sentence concrete reasoning. Cite specific assumption being challenged.]

2. ...
3. ...
```

### 2. **Confirmation-Bias Audit (data / assumption cherry-picking risk)**

Identify where the user is **likely cherry-picking** — facts they're emphasizing because they support the conclusion they already want, while quietly down-weighting disconfirming evidence. Be specific:
- Which numbers / sources / examples did they emphasize?
- What contradicting numbers / sources / examples did they NOT mention?
- What's the strongest piece of data that, if surfaced, would weaken their case?

If there isn't clear cherry-picking risk, say so plainly: "I don't see strong cherry-picking signal here." Don't manufacture criticism.

### 3. **1-Year Pre-Mortem**

Write a short paragraph dated **one year from today**, assuming this decision turned out wrong. The paragraph must:
- State the concrete failure outcome (not "it didn't work" — say what specifically happened)
- Identify the single root cause (not a list of 5 contributing factors)
- Name the **earliest warning signal** the user could have seen if they'd been watching for it

Format:
```
[YYYY-MM-DD]: This decision / plan failed. What specifically happened: [concrete outcome].
Root cause: [single root cause].
The earliest warning signal was [specific observable signal] — if watched for, the decision could have been reversed within [time window].
```

---

## WHEN NOT TO USE THIS SKILL

Do NOT invoke devil's advocate when:
- The user is asking a factual question (e.g., "what's NVDA's last close?")
- The user is asking how to do something (e.g., "how do I deploy this?")
- The user is venting or sharing news without seeking judgment
- The user has explicitly said "I just want to ship, don't argue with me"
- The user has already heard your devil's advocate output and is now asking follow-up questions on a specific point — those are normal conversation, not a second devil's advocate pass

If unsure whether the user wants adversarial review or normal help, **ask** before invoking: "Do you want me to just execute this, or pressure-test it first?"

---

## CONTEXTUAL ADJUSTMENTS BY PROFILE

The skill is the same across profiles, but emphasis differs:

- **WH 文豪 (writer)**: Apply to article angles, titles, hooks, framing decisions. Section 1 attacks the angle's reader-resonance. Section 2 audits which past articles the user is over-weighting. Section 3 imagines the post failing to land.

- **CIO (pm)**: Apply to investment theses, position sizing, sector calls. Section 1 attacks the thesis from the strongest bear case. Section 2 audits which data sources / analysts the user is over-trusting. Section 3 imagines the position turning -30%+.

- **CTO/COO (manager)**: Apply to system designs, automation plans, agent architectures. Section 1 attacks the design's failure modes. Section 2 audits which assumptions about reliability / scale were unstated. Section 3 imagines the system in production failing badly.

- **Legacy / general**: Apply generically — the 3-section format is the contract.

---

## HARD RULES

1. **No softening.** Do not start with praise. Do not end with reassurance.
2. **No false balance.** If the plan is genuinely strong, say so in section 2 ("I don't see strong cherry-picking") — but don't manufacture weak objections to fill section 1.
3. **No hallucinated data.** If you cite a number or a precedent, it must be real (or marked as "assumption / illustrative").
4. **Stay in scope.** Only adversarialize what the user submitted. Don't drag in unrelated decisions.
5. **End at section 3.** No closing "but ultimately the choice is yours" — that defeats the point.
6. After the 3 sections, you may add ONE clarifying question if there's genuinely ambiguous scope. Otherwise stop.

---

## OUTPUT EXAMPLE (illustrative — do NOT copy verbatim)

User: `/devil I'm about to add 200 shares of NVDA at $209 because the AI cycle isn't over yet`

Output:
```
### 1. Strongest Counter-Arguments

1. **The AI capex inflection may come earlier than you expect**
   → 70%+ of NVDA revenue comes from hyperscaler capex; recent META and GOOGL earnings already suggest 2026 H2 capex growth may slow from +60% to +20%. "The cycle isn't over" rests on trailing-12-month data, but the second derivative may already be turning down.

2. **Your position concentration is already too heavy**
   → NVDA is already the single largest position in your US book (≈$170k cost / 828 shares). Adding 200 more pushes single-name concentration past 25% — beyond your own 10% single-name cap (from portfolio_rules.json). Rationally you should be trimming, not adding.

3. **$209 is not a low**
   → Only 3.4% off the 52-week high of $216, and still 14% above MA200. Technically, "adding" usually waits for a pullback to MA50 or lower. Adding here is chasing strength, not allocating.

### 2. Confirmation-Bias Audit

You emphasize "the AI cycle isn't over" — which is true, but you **did not mention**:
- Your own last `port health` already flagged NVDA as "Reduce / confidence 80" (Meta plunged -9%, semi-sector correlation risk rising)
- Your portfolio decisions weekly flagged "hedge ratio < target" last week — the system is telling you your hedge is insufficient, not to add risk assets
- You haven't touched AAPL, another AI-theme name, recently — why single out NVDA?

Strongly suggest re-reading that "single name cap 10%" rule.

### 3. 1-Year Pre-Mortem

2027-05-20: This add lost -38%. After NVDA's 2026 Q4 guidance missed, it slid from $209 into the $130 range because hyperscaler 2027 capex growth slowed further from +20% to +5%. Root cause: adding at a valuation high + breaching your own concentration cap + ignoring a system Reduce signal, all at once. The earliest warning signal was the first capex-growth downgrade in META's 2026 Q3 earnings — if watched for, the decision could have been reversed within 6 weeks (or switched to AAPL or SOXX to diversify).
```
