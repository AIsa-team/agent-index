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
        "name": "US equities",
        "indices": [
            ("^GSPC", "S&P 500"),
            ("^IXIC", "Nasdaq Composite"),
            ("^DJI", "Dow Jones"),
            ("^VIX", "VIX volatility"),
        ],
        "sectors": [
            ("XLK", "Technology"),
            ("XLF", "Financials"),
            ("XLV", "Health Care"),
            ("XLE", "Energy"),
            ("XLY", "Consumer Discretionary"),
            ("XLP", "Consumer Staples"),
            ("XLI", "Industrials"),
            ("XLB", "Materials"),
            ("XLU", "Utilities"),
        ],
    },
    "HK": {
        "name": "HK equities",
        "indices": [
            ("^HSI", "Hang Seng Index"),
            ("^HSCE", "Hang Seng China Enterprises"),
            ("^HSTECH", "Hang Seng Tech"),
        ],
        "sectors": [
            ("0700.HK", "Hang Seng Tech ETF"),
            ("2828.HK", "Hang Seng Index ETF"),
            ("2800.HK", "Tracker Fund of HK"),
        ],
    },
}


BRIEF_SYSTEM_PROMPT = """You are a seasoned market strategist. Based on the day's index and sector data the user provides, output a DSA-style English market brief (Markdown format).

The output contains 4 sections (separated by Markdown level-2 headings):

## 1. Index Overview
List each index's move for the day (format: index name, close (+x.xx%)), and give an overall direction call (<=2 sentences).

## 2. Sector Rotation
Sort by the day's move; flag the top 3 gainers and bottom 3 laggards; comment in 1 sentence on the rotation signal (risk-on / risk-off / tech rebound, etc.).

## 3. Key Observations
3-5 bullet points (price-volume relationship, sentiment gauges like VIX, breakouts/pullbacks, names worth tracking). Keep each short.

## 4. Action Ideas
2-3 execution-oriented ideas (note: not single-stock recommendations, but position/pace guidance, e.g. "trim into strength, take a light probe on breakout sectors").

Hard rules:
- Base everything strictly on the provided data; do not fabricate any "news / earnings / policy"
- Numbers must be concrete, direction must be clear
- No preamble and no concluding wrap-up paragraph — output the four sections directly
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
    lines = [f"Date: {date.today().isoformat()}", f"Market: {market_data['market']}", "", "[Indices]"]
    for idx in market_data["indices"]:
        if "error" in idx:
            lines.append(f"  {idx['label']} ({idx['ticker']}): data missing")
            continue
        lines.append(
            f"  {idx['label']} ({idx['ticker']}): {idx['last']} ({idx['pct_1d']:+.2f}%) "
            f"MA20={idx['ma20']} MA50={idx['ma50']} RSI={idx['rsi14']} from high {idx['pct_from_52w_high']:+.1f}%"
        )
    lines.append("")
    lines.append("[Sectors/ETFs]")
    for sec in market_data["sectors"]:
        if "error" in sec:
            lines.append(f"  {sec['label']} ({sec['ticker']}): data missing")
            continue
        vr = sec.get("vol_ratio")
        vr_str = f"vol={vr}x" if vr else ""
        lines.append(f"  {sec['label']} ({sec['ticker']}): {sec['last']} ({sec['pct_1d']:+.2f}%) {vr_str}")
    lines.append("")
    lines.append("Output the market brief per the system prompt.")
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

    title = f"📈 *{md['market']} market brief* — {date.today().isoformat()}"
    full = f"{title}\n\n{body}\n\n_via {resp.model} · {elapsed:.1f}s_"

    # Full brief between markers — the Hermes agent delivers it on its reply channel
    emit_report(f"{full}\n\n---\n\nDONE: {args.market} brief ({elapsed:.1f}s, model={resp.model})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
