#!/usr/bin/env python3
"""
dsa_scan.py — Single/multi-ticker quick scan (DSA-style decision dashboard).

Triggered by Hermes when user types:
  scan TICKER [TICKER ...]
  扫 TICKER [TICKER ...]
  quick TICKER [TICKER ...]

Behavior:
  1. Fetch OHLCV via yfinance for each ticker
  2. Compute technicals (MA / RSI / MACD / volume)
  3. Call Gemini-2.5-flash (no thinking) → DeepSeek-v4-flash fallback
  4. Render DSA-style "decision dashboard" markdown for each ticker
  5. Emit all dashboards + a summary status line between
     __REPORT_START__ / __REPORT_END__ markers on stdout — the Hermes agent
     reads them and delivers over its own reply channel
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Make sibling _dsa_lib importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _dsa_lib import (  # noqa: E402
    call_llm_dashboard,
    emit_report,
    fetch_snapshot,
    format_dashboard,
    load_env,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="DSA-style quick scan for one or more tickers")
    ap.add_argument("tickers", nargs="+", help="e.g. NVDA MSFT 0700.HK")
    ap.add_argument("--profile", default="fast_scan", choices=["fast_scan", "deep_research"])
    args = ap.parse_args()

    # Cap to avoid accidentally scanning a huge list
    if len(args.tickers) > 8:
        print(f"[guard] too many tickers ({len(args.tickers)}); cap is 8 per call", file=sys.stderr)
        return 2

    load_env()
    successes: list[str] = []
    failures: list[str] = []
    reports: list[str] = []

    for ticker in args.tickers:
        ticker = ticker.strip().upper()
        # Preserve known suffix casing
        for suffix in (".HK", ".T", ".SS", ".SZ", ".SI", ".KS"):
            if ticker.endswith(suffix.upper()):
                ticker = ticker.replace(suffix.upper(), suffix)

        print(f"[scan] {ticker} fetching…", file=sys.stderr)
        snap = fetch_snapshot(ticker)
        if not snap:
            failures.append(f"{ticker}: no data")
            print(f"[scan] {ticker} no data", file=sys.stderr)
            continue

        print(f"[scan] {ticker} analyzing…", file=sys.stderr)
        t0 = time.time()
        data = call_llm_dashboard(snap, profile=args.profile)
        elapsed = time.time() - t0
        if not data:
            failures.append(f"{ticker}: LLM failed")
            continue

        body = format_dashboard(data)
        print(f"[scan] {ticker} done in {elapsed:.1f}s via {data.get('_meta',{}).get('model','?')}",
              file=sys.stderr)

        reports.append(body)
        successes.append(ticker)

    # Full dashboards + summary status line for Hermes (between markers)
    summary_lines = []
    if successes:
        summary_lines.append(f"DONE: scanned {len(successes)} ticker(s) → {', '.join(successes)}")
    if failures:
        summary_lines.append(f"FAILED: {len(failures)} — {'; '.join(failures)}")
    if not summary_lines:
        summary_lines.append("DONE: no tickers processed")

    emit_report("\n\n---\n\n".join(reports + ["\n".join(summary_lines)]))
    return 0 if successes else 1


if __name__ == "__main__":
    sys.exit(main())
