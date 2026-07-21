---
name: portfolio-update
description: "AUTO-INVOKE when user reports a portfolio change in natural language (我买了/卖了/加仓/减仓/清仓/新开仓/现金或MMF更新到/改成本价, bought/sold/trimmed/exited), or says 'port update'. Guides holdings updates via update_holdings.py — never hand-edit portfolio_truth.json."
---

> **Data bootstrap** — this skill reads files under the user data directory.
> If a path below does not exist yet, run `bash "${PLUGIN_ROOT}/scripts/ensure-data.sh"` first
> (idempotent: seeds missing files from the plugin's bundled assets, never overwrites existing data).
> - `~/.aisa/agents/cio/portfolio` — 组合数据目录（portfolio_truth.json / 引擎脚本）(export `PORTFOLIO_DIR` to override — if set, use its value instead of this default)

# Portfolio Update — 持仓变更引导

把用户的自然语言持仓变更翻译成 `update_holdings.py` 命令：写入前确认、写入自动快照、写入后可验证。

**脚本**：`python3 ~/.aisa/agents/cio/portfolio/update_holdings.py`

| 命令 | 作用 |
|---|---|
| `list` | 列出全部持仓（index/name/ticker/qty/cost/ccy） |
| `buy TICKER QTY PRICE [--lot N]` | 加仓（加权平均成本） |
| `sell TICKER QTY [--lot N]` | 减仓（成本不变；卖到 0 保留行并提示 remove） |
| `add TICKER QTY PRICE [--name NAME] [--ccy CCY]` | 新增标的（币种按后缀推断：.HK→HKD、.T→JPY、.SI→SGD、默认 USD） |
| `remove TICKER [--lot N]` | 清仓删行（删除前打印整行） |
| `set TICKER cost\|qty AMOUNT [--lot N]` | 改成本/数量 |
| `set NAME value AMOUNT` | 现金/静态项估值（Cash、MMF、MMF2、PrivateFund、PrivateBiz、StructNote） |

## 工作流（硬流程，逐步执行）

1. **解析** — 从用户话语提取 action / ticker / qty / price。缺参数就追问，一次只问一个（例：只说"买了点 NVDA" → 先问数量，再问成交价）。
2. **核对** — 先跑 `list`（terminal 执行），绝不凭记忆假设持仓：
   - 标的不在列表 → 走 `add`（向用户确认全名与币种）；
   - 标的在列表 → 走 `buy`/`sell`/`set`；
   - 同一 ticker 多个 lot → 把 lot 列表展示给用户，让用户选 `--lot N`。
3. **确认** — 复述完整变更再等用户明确同意，例：
   「NVDA 买入 100 股 @ USD 202.50 → 持仓 100→200 股，加权平均成本约 151.25。确认执行？」
   **用户未明确同意前，绝不执行任何写入命令。**
4. **执行** — 跑对应命令一次，把脚本输出（含 before/after 与 `📸 snapshot:` 行）**原样**转发给用户。输出必须含 `✅` 与 `snapshot:`；缺任一 → 视为失败，展示错误原文，不要重试、不要伪造结果。
5. **校验** — 提示用户可跑 `port` 查看更新后实时估值。若执行失败或用户要撤销：最近快照在 `~/.aisa/agents/cio/portfolio/snapshots/`，回滚 = 把快照复制回 `portfolio_truth.json`（需用户确认后执行 `cp`）。

## `port update` 引导模式

用户输入 `port update` 时：先跑 `list` 展示当前持仓，然后问「要改哪一项？（加仓/减仓/新增/清仓/改成本/改现金）」，进入上面同一工作流。

## 硬规则

- **绝不手动编辑 `portfolio_truth.json`** — 一切写入走 `update_holdings.py`。
- 数量/价格/金额必须来自用户原话或用户确认，**绝不推测补全**。
- 一次对话可处理多笔变更，但**逐笔确认、逐笔执行**。
- 全部变更完成后，建议用户跑 `port` 验证。
