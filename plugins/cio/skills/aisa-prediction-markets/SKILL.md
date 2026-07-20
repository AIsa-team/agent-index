---
name: aisa-prediction-markets
description: AIsa Prediction Market Data — 统一 Polymarket + Kalshi 预测市场数据：市场列表、实时价格、K线图、订单簿、钱包活动、P&L、跨平台匹配。CIO 追踪政治/经济/事件定价。
auto_invoke_on:
  - "预测市场"
  - "Polymarket"
  - "Kalshi"
  - "博弈市场"
  - "事件定价"
  - "预测市场数据"
  - "事件合约"
---

# AIsa Prediction Market Data

**统一 Polymarket + Kalshi 预测市场数据。** 一个 API 覆盖两个最大预测市场平台。

## 何时使用 (CIO)

- **追踪事件定价** — 大选、FOMC、监管、地缘政治
- **市场情绪指标** — 某个事件的隐含概率
- **跨平台套利** — `sports-matching` 找 Polymarket vs Kalshi 同一事件的价差
- **K线分析** — 预测合约的价格走势

## 使用方法

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/aisa-prediction-markets/scripts/call.py prediction <action> [options]
```

### 可用操作

**Polymarket:**

| Action | 用途 | 参数 |
|--------|------|------|
| `poly-markets` | 市场列表 | `--search` |
| `poly-events` | 所有事件 | 无 |
| `poly-price` | 某个市场实时价 | `--token-id` |
| `poly-orderbook` | 订单簿深度 | `--token-id` |
| `poly-candles` | K线图数据 | `--token-id` |
| `poly-activity` | 钱包交易记录 | `--wallet` |
| `poly-pnl` | 钱包盈亏 | `--wallet` |

**Kalshi:**

| Action | 用途 | 参数 |
|--------|------|------|
| `kalshi-markets` | 市场列表 | `--search` |
| `kalshi-price` | 实时价格 | `--ticker` |
| `kalshi-trades` | 成交记录 | `--ticker` |
| `kalshi-orderbook` | 订单簿 | `--ticker` |

**跨平台:**

| Action | 用途 | 参数 |
|--------|------|------|
| `sports-matching` | 跨平台匹配市场 | `--sport`, `--date` |

### 典型用例

```bash
# 查看所有活跃的 Polymarket 市场
python3 ${CLAUDE_PLUGIN_ROOT}/skills/aisa-prediction-markets/scripts/call.py prediction poly-markets

# 搜索 "Fed" 相关预测市场
python3 ${CLAUDE_PLUGIN_ROOT}/skills/aisa-prediction-markets/scripts/call.py prediction poly-markets --search "Fed rate cut"

# 查看 Kalshi 上 "BTC" 相关合约
python3 ${CLAUDE_PLUGIN_ROOT}/skills/aisa-prediction-markets/scripts/call.py prediction kalshi-markets --search "BTC"

# 获取某个合约的价格 (需要先查到 token_id)
python3 ${CLAUDE_PLUGIN_ROOT}/skills/aisa-prediction-markets/scripts/call.py prediction poly-price --token-id 12345

# 跨平台体育匹配
python3 ${CLAUDE_PLUGIN_ROOT}/skills/aisa-prediction-markets/scripts/call.py prediction sports-matching --sport nba --date 2026-06-01
```

## 成本
- 按次调用计费，约 $0.02/次
