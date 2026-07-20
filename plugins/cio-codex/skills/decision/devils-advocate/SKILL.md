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

### 1. **三个最强反对论据 (Strongest Counter-Arguments)**

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

### 2. **数据 / 假设的 cherry-picking 风险 (Confirmation-Bias Audit)**

Identify where the user is **likely cherry-picking** — facts they're emphasizing because they support the conclusion they already want, while quietly down-weighting disconfirming evidence. Be specific:
- Which numbers / sources / examples did they emphasize?
- What contradicting numbers / sources / examples did they NOT mention?
- What's the strongest piece of data that, if surfaced, would weaken their case?

If there isn't clear cherry-picking risk, say so plainly: "I don't see strong cherry-picking signal here." Don't manufacture criticism.

### 3. **一年后的失败复盘 (1-Year Pre-Mortem)**

Write a short paragraph dated **one year from today**, assuming this decision turned out wrong. The paragraph must:
- State the concrete failure outcome (not "it didn't work" — say what specifically happened)
- Identify the single root cause (not a list of 5 contributing factors)
- Name the **earliest warning signal** the user could have seen if they'd been watching for it

Format:
```
[YYYY-MM-DD]: 这个决定 / 计划失败了。具体表现：[concrete outcome]。
根本原因：[single root cause]。
最早的预警信号是 [specific observable signal] — 当时如果留意，能在 [time window] 内反转决定。
```

---

## WHEN NOT TO USE THIS SKILL

Do NOT invoke devil's advocate when:
- The user is asking a factual question (e.g., "what's NVDA's last close?")
- The user is asking how to do something (e.g., "how do I deploy this?")
- The user is venting or sharing news without seeking judgment
- The user has explicitly said "I just want to ship, don't argue with me"
- The user has already heard your devil's advocate output and is now asking follow-up questions on a specific point — those are normal conversation, not a second devil's advocate pass

If unsure whether the user wants adversarial review or normal help, **ask** before invoking: "你想让我直接帮你执行，还是先 devil 一下？"

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
3. **No hallucinated data.** If you cite a number or a precedent, it must be real (or marked as "假设 / illustrative").
4. **Stay in scope.** Only adversarialize what the user submitted. Don't drag in unrelated decisions.
5. **End at section 3.** No closing "but ultimately the choice is yours" — that defeats the point.
6. After the 3 sections, you may add ONE clarifying question if there's genuinely ambiguous scope. Otherwise stop.

---

## OUTPUT EXAMPLE (illustrative — do NOT copy verbatim)

User: `/devil 我准备加仓 NVDA 200 股，现价 $209，因为 AI 周期还没结束`

Output:
```
### 1. 三个最强反对论据

1. **AI 资本开支拐点可能比你预期早**
   → NVDA 收入 70%+ 来自 hyperscaler capex；近期 META、GOOGL 财报已显示 2026 H2 capex 增速可能从 +60% 降到 +20%。"周期还没结束"这个判断依据的是 trailing 12 月数据，但二阶导可能已经向下。

2. **你的仓位 concentration 已经过重**
   → NVDA 在你美股仓位里占比已是单一最大头寸（≈$170k cost / 828 股）。再加 200 股会让单股集中度突破 25%——这超过了你自己定的 10% single-name cap（来自 portfolio_rules.json）。理性的话，你应该减仓而不是加仓。

3. **$209 不是低位**
   → 离 52 周高 $216 只差 3.4%，距 MA200 还高 14%。"加仓"在技术面通常等待回调到 MA50 或更低。此刻加仓是追涨，不是配置。

### 2. Cherry-picking 审计

你强调的是"AI 周期还没结束"——这是真的，但你**没有提及**：
- 你自己上次 `port health` 报告 NVDA 已经显示"减持 / 置信 80"（meta 已暴跌 -9%，semi 板块联动风险升高）
- 你的 portfolio decisions weekly 上周提示了"hedge ratio < target"——意味着系统在告诉你 hedge 不够，不是加风险资产
- 同样是 AI 主题的 AAPL 你最近没动 — 为什么独独看好 NVDA？

强烈建议把"single name cap 10%"那条规则拿出来再看一遍。

### 3. 一年后失败复盘

2027-05-20: 这次加仓亏损 -38%。NVDA 在 2026 Q4 财报 guidance 不及预期后从 $209 滑到 $130 区间，原因是 hyperscaler 2027 capex 增速从 +20% 进一步降到 +5%。根本原因：在估值高位 + 自己设定的 concentration 上限被突破 + 系统已经给出减持信号 时，仍然加仓。最早的预警信号是 META 2026 Q3 财报里 capex 增速首次下修——当时如果留意，能在 6 周内反转决定（甚至改成 AAPL 或 SOXX 分散仓位）。
```
