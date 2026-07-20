---
name: aisa-last30days
description: AIsa Last30Days — 30天多源社交媒体扫描。覆盖 Reddit、X/Twitter、YouTube、TikTok、Instagram、Hacker News、Polymarket、Web Search 八个平台。为 Writer(WH文豪) 提供热点选题发现能力。
auto_invoke_on:
  - "找热点"
  - "话题发现"
  - "最近30天"
  - "选题"
  - "热门话题"
  - "社交媒体趋势"
  - "写什么好"
  - "灵感枯竭"
---

# AIsa Last30Days

**30 天多源社交媒体扫描。** 覆盖 8 个平台，返回聚类排序的话题简报。

## 何时使用 (Writer / WH)

- **写前扫热点** — 了解某个话题在过去 30 天的讨论热度
- **选题灵感** — 看到大家都在讨论什么，决定写什么
- **竞品监测** — 了解某个领域的 KOL 在发什么内容
- **读者兴趣探测** — 看哪些话题有高回复/高互动

## 使用方法

```bash
python3 ${PLUGIN_ROOT}/skills/aisa-last30days/scripts/call.py --topic "主题" [--deep]
```

### 参数

| 参数 | 说明 |
|------|------|
| `--topic` | 搜索主题（必填） |
| `--deep` | 深度模式：扩大候选池，包含更多来源和更久时间范围 |

### 典型用例

```bash
# 写文章前扫一下 "AI agent" 话题热度
python3 ${PLUGIN_ROOT}/skills/aisa-last30days/scripts/call.py --topic "AI agent business model"

# 深度扫描：了解 "DeepSeek" 在各平台的讨论
python3 ${PLUGIN_ROOT}/skills/aisa-last30days/scripts/call.py --topic "DeepSeek" --deep

# 选题灵感：看科技圈最近30天最火的话题
python3 ${PLUGIN_ROOT}/skills/aisa-last30days/scripts/call.py --topic "technology trends"

# 竞品分析：某个 KOL 领域最近30天的讨论
python3 ${PLUGIN_ROOT}/skills/aisa-last30days/scripts/call.py --topic "value investing 2026"
```

## 覆盖平台

1. Reddit — 社区讨论
2. X/Twitter — 实时话题
3. YouTube — 视频内容
4. TikTok — 短视频热点
5. Instagram — 视觉话题
6. Hacker News — 技术圈
7. Polymarket — 事件定价
8. Web Search — 全网搜索

## 工作流建议

1. 用 `last30days --topic "XXX"` 扫热点
2. 用 `aisa-search deep-research --query "XXX"` 挖深度信息
3. 用 `aisa-twitter tweet-search --query "XXX"` 找最新讨论
4. 写文章

## 成本
- 按次调用计费，约 $0.02/次
