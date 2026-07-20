---
name: aisa-search
description: AIsa Multi-source Search — 多源搜索：网页搜索、学术论文、Perplexity Sonar 四个层次（fast/synthesis/reasoning/deep-research）、Tavily（search/extract/crawl/map）。替代 web_search 和 Perplexity 独立订阅。
auto_invoke_on:
  - "搜索研究"
  - "查论文"
  - "深度研究"
  - "学术搜索"
  - "抓取网页内容"
  - "爬虫"
  - "信息检索"
  - "引文搜索"
---

# AIsa Multi-source Search

**统一的多源搜索引擎。** 一个 API Key 覆盖网页、学术、Perplexity 和 Tavily。

## 何时使用

- **替代 `web_search`** — 结果更结构化，支持学术和深度研究
- **做投资研究** — 用 `deep-research` 生成 2000+ 字的深度报告
- **查学术论文** — 用 `scholar` 查最新研究成果
- **提取网页内容** — 用 `tavily-extract` 获取干净正文
- **爬取文档网站** — 用 `tavily-crawl` 递归抓取

## 使用方法

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/aisa-search/scripts/call.py search <action> [options]
```

### 可用操作

| Action | 用途 | 参数 |
|--------|------|------|
| `web` | 结构化网页搜索 | `--query` |
| `scholar` | 学术论文搜索 | `--query` |
| `mixed` | Web + Scholar 混合 | `--query` |
| `sonar` | Perplexity Sonar 快速回答 | `--query` |
| `sonar-pro` | Sonar Pro 综合回答 | `--query` |
| `sonar-reasoning` | Sonar Reasoning Pro | `--query` |
| `deep-research` | 深度研究报告 | `--query` |
| `tavily-search` | Tavily 搜索 | `--query` |
| `tavily-extract` | 提取网页正文 | `--urls` |
| `tavily-crawl` | 递归爬取 | `--url`, `--depth` |
| `tavily-map` | 站点地图 | `--url` |

### 典型场景

```bash
# 投资研究 — 深度报告
python3 ${CLAUDE_PLUGIN_ROOT}/skills/aisa-search/scripts/call.py search deep-research --query "AI agent market size and key players 2026"

# 快速事实核查
python3 ${CLAUDE_PLUGIN_ROOT}/skills/aisa-search/scripts/call.py search sonar --query "What is the latest Fed rate decision?"

# 论文搜索
python3 ${CLAUDE_PLUGIN_ROOT}/skills/aisa-search/scripts/call.py search scholar --query "transformer architecture attention mechanism"

# 抓取多篇文章正文
python3 ${CLAUDE_PLUGIN_ROOT}/skills/aisa-search/scripts/call.py search tavily-extract --urls "https://example.com/article1,https://example.com/article2"

# 爬取文档站
python3 ${CLAUDE_PLUGIN_ROOT}/skills/aisa-search/scripts/call.py search tavily-crawl --url "https://docs.example.com" --depth 2
```

## 选择指南

| 需求 | 用哪个 |
|------|--------|
| 快速查事实 | `sonar` |
| 全面研究 | `sonar-pro` |
| 需要推理分析 | `sonar-reasoning` |
| 深度研究报告 | `deep-research` |
| 学术论文 | `scholar` |
| 网页正文提取 | `tavily-extract` |
| 多源混合 | `mixed` |
