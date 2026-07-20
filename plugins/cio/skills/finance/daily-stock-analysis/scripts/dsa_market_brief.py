#!/usr/bin/env python3
"""
dsa_market_brief.py — Index/sector market overview for HK or US.

Triggered by Hermes when user types:
  market brief
  brief HK
  brief US
  市场简报
  市场简报 US

Pulls major indices + sector ETFs via yfinance, summarizes via LLM into a
DSA-style market review. No A-share coverage (per user requirement).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _dsa_lib import (  # noqa: E402
    emit_report,
    fetch_snapshot,
    get_router,
    load_env,
)


# Market definitions: indices + representative sector ETFs
MARKETS = {
    "US": {
        "name": "美股",
        "indices": [
            ("^GSPC", "S&P 500"),
            ("^IXIC", "Nasdaq Composite"),
            ("^DJI", "Dow Jones"),
            ("^VIX", "VIX 波动率"),
        ],
        "sectors": [
            ("XLK", "科技"),
            ("XLF", "金融"),
            ("XLV", "医疗"),
            ("XLE", "能源"),
            ("XLY", "消费可选"),
            ("XLP", "消费必需"),
            ("XLI", "工业"),
            ("XLB", "材料"),
            ("XLU", "公用事业"),
        ],
    },
    "HK": {
        "name": "港股",
        "indices": [
            ("^HSI", "恒生指数"),
            ("^HSCE", "恒生中国企业"),
            ("^HSTECH", "恒生科技"),
        ],
        "sectors": [
            ("0700.HK", "恒生科技 ETF"),
            ("2828.HK", "恒生指数 ETF"),
            ("2800.HK", "盈富基金"),
        ],
    },
}


BRIEF_SYSTEM_PROMPT = """你是一位资深的市场策略分析师。根据用户提供的当日指数和板块数据，输出 DSA 风格的中文市场简报（Markdown 格式）。

输出包含 4 个段落（用 Markdown 二级标题分隔）：

## 一、指数概览
逐个指数列出当日涨跌（格式：指数名 收盘价 (+x.xx%)），并给出整体方向判断（≤2 句）。

## 二、板块轮动
按当日涨跌幅排序，标出领涨 3 个、领跌 3 个板块；用 1 句话点评轮动信号（风险偏好/避险/科技回暖等）。

## 三、关键观察
3-5 条要点（量价关系、情绪指标如 VIX、突破/回撤、值得后续跟踪的标的）。每条 ≤30 字。

## 四、行动建议
2-3 条偏向操作的建议（注意：不是个股推荐，而是仓位/节奏建议，例如"减仓追高、轻仓试探突破板块"）。

铁律：
- 完全基于提供的数据，不要编造任何"消息面/财报/政策"
- 数字要具体，方向要明确
- 不要前言、不要总结性末段，直接四个段落输出
"""


def fetch_index_data(market_key: str) -> dict:
    """Fetch indices and sectors for a market into a dict suitable for LLM context."""
    cfg = MARKETS[market_key]
    out: dict = {"market": cfg["name"], "indices": [], "sectors": []}
    for ticker, label in cfg["indices"]:
        snap = fetch_snapshot(ticker, period="3mo")
        if snap:
            out["indices"].append({
                "ticker": ticker,
                "label": label,
                "last": snap.last_close,
                "pct_1d": snap.pct_change_1d,
                "ma20": snap.ma20,
                "ma50": snap.ma50,
                "rsi14": snap.rsi14,
                "pct_from_52w_high": snap.pct_from_52w_high,
            })
        else:
            out["indices"].append({"ticker": ticker, "label": label, "error": "no data"})

    for ticker, label in cfg["sectors"]:
        snap = fetch_snapshot(ticker, period="3mo")
        if snap:
            out["sectors"].append({
                "ticker": ticker,
                "label": label,
                "last": snap.last_close,
                "pct_1d": snap.pct_change_1d,
                "vol_ratio": snap.volume_ratio_20d,
            })
        else:
            out["sectors"].append({"ticker": ticker, "label": label, "error": "no data"})
    return out


def build_brief_prompt(market_data: dict) -> str:
    """Render compact market data into a user prompt for the LLM."""
    lines = [f"日期：{date.today().isoformat()}", f"市场：{market_data['market']}", "", "【指数】"]
    for idx in market_data["indices"]:
        if "error" in idx:
            lines.append(f"  {idx['label']} ({idx['ticker']}): 数据缺失")
            continue
        lines.append(
            f"  {idx['label']} ({idx['ticker']}): {idx['last']} ({idx['pct_1d']:+.2f}%) "
            f"MA20={idx['ma20']} MA50={idx['ma50']} RSI={idx['rsi14']} 距高 {idx['pct_from_52w_high']:+.1f}%"
        )
    lines.append("")
    lines.append("【板块/ETF】")
    for sec in market_data["sectors"]:
        if "error" in sec:
            lines.append(f"  {sec['label']} ({sec['ticker']}): 数据缺失")
            continue
        vr = sec.get("vol_ratio")
        vr_str = f"vol={vr}x" if vr else ""
        lines.append(f"  {sec['label']} ({sec['ticker']}): {sec['last']} ({sec['pct_1d']:+.2f}%) {vr_str}")
    lines.append("")
    lines.append("请按系统提示输出市场简报。")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="DSA market brief (HK or US)")
    ap.add_argument("market", choices=["HK", "US"], help="HK or US (no A-share)")
    args = ap.parse_args()

    load_env()
    print(f"[brief] {args.market} fetching index/sector data…", file=sys.stderr)
    md = fetch_index_data(args.market)

    print(f"[brief] {args.market} calling LLM…", file=sys.stderr)
    router = get_router("fast_scan")
    t0 = time.time()
    try:
        resp = router.completion(
            model="fast_scan",
            messages=[
                {"role": "system", "content": BRIEF_SYSTEM_PROMPT},
                {"role": "user", "content": build_brief_prompt(md)},
            ],
            max_tokens=2500,
        )
    except Exception as e:
        emit_report(f"FAILED: LLM call failed — {e}")
        return 1
    elapsed = time.time() - t0

    body = (resp.choices[0].message.content or "").strip()
    if not body:
        emit_report("FAILED: LLM returned empty response")
        return 1

    title = f"📈 *{md['market']}市场简报* — {date.today().isoformat()}"
    full = f"{title}\n\n{body}\n\n_via {resp.model} · {elapsed:.1f}s_"

    # Full brief between markers — the Hermes agent delivers it on its reply channel
    emit_report(f"{full}\n\n---\n\nDONE: {args.market} brief ({elapsed:.1f}s, model={resp.model})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
