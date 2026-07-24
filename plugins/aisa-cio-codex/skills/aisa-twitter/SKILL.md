---
name: aisa-twitter
description: AIsa Twitter Autopilot — X/Twitter 全量读取能力：用户信息、推文历史、搜索、趋势、回复、引用、转发、话题上下文。不需 OAuth，成本远低于官方 API。CIO 追踪市场情绪，Writer 追踪热点话题和 KOL。
auto_invoke_on:
  - "看推文"
  - "Twitter搜索"
  - "趋势"
  - "KOL说了什么"
  - "市场情绪"
  - "热点话题"
  - "X上"
  - "推特"
  - "某人最近发推"
  - "关注者"
---

# AIsa Twitter Autopilot

**X/Twitter 全量读取能力，无需 OAuth。** 一个 API Key 即可获取所有公开数据。

## 双 Agent 使用场景

### CIO（投资研究）
- **追踪市场情绪** — 搜索关键词、关注 KOL、看趋势
- **名人动态** — 快速查看某投资大佬最近说了什么
- **推文搜索** — "AI bubble" 最新讨论、特定 ticker 提及

### Writer / WH 文豪（内容创作）
- **热点话题发现** — 看 `trends` 找今天热什么
- **竞品监测** — 关注同行 KOL 的最新推文
- **素材搜集** — 搜索特定话题看最近讨论

## 使用方法

```bash
python3 ${PLUGIN_ROOT}/skills/aisa-twitter/scripts/call.py twitter <action> [options]
```

### 可用操作

| Action | 用途 | 参数 |
|--------|------|------|
| `user` | 用户资料 | `--username` |
| `tweets` | 最新推文 | `--username` |
| `mentions` | 被 @ 记录 | `--username` |
| `followers` | 关注者列表 | `--username` |
| `followings` | 正在关注 | `--username` |
| `user-search` | 搜索用户 | `--query` |
| `tweet-search` | 高级推文搜索 | `--query`, `--query-type` |
| `tweets-by-id` | 按 ID 查推文 | `--tweet-ids` |
| `replies` | 推文回复 | `--tweet-id` |
| `quotes` | 引用转发 | `--tweet-id` |
| `retweeters` | 转发者列表 | `--tweet-id` |
| `thread` | 线程上下文 | `--tweet-id` |
| `trends` | 全球/地区趋势 | `--woeid` |
| `article` | 推文内文章 | `--tweet-id` |

### 典型用例

```bash
# CIO: 看 Elon Musk 最近说了什么
python3 ${PLUGIN_ROOT}/skills/aisa-twitter/scripts/call.py twitter tweets --username elonmusk

# CIO: 搜索 "NVIDIA earnings" 的讨论
python3 ${PLUGIN_ROOT}/skills/aisa-twitter/scripts/call.py twitter tweet-search --query "NVIDIA earnings" --query-type Latest

# CIO: 查一个 KOL 的影响力
python3 ${PLUGIN_ROOT}/skills/aisa-twitter/scripts/call.py twitter user --username aantonop

# Writer: 看今天全球趋势
python3 ${PLUGIN_ROOT}/skills/aisa-twitter/scripts/call.py twitter trends --woeid 1

# Writer: 搜索 "AI agent" 话题看热度
python3 ${PLUGIN_ROOT}/skills/aisa-twitter/scripts/call.py twitter tweet-search --query "AI agent" --query-type Top

# Writer: 看某个话题线程
python3 ${PLUGIN_ROOT}/skills/aisa-twitter/scripts/call.py twitter thread --tweet-id 1234567890123456789

# CIO: 新加坡趋势 (WOEID 23424948)
python3 ${PLUGIN_ROOT}/skills/aisa-twitter/scripts/call.py twitter trends --woeid 23424948
```

## 常用 WOEID
- `1` = 全球
- `23424948` = 新加坡
- `23424977` = 美国
- `2442047` = 中国

## 注意
- 按次调用计费，约 $0.02/次，远低于 X 官方 API（$100-5k/月）
- 仅读取，不发送推文
- 不需要申请 OAuth 开发者权限
