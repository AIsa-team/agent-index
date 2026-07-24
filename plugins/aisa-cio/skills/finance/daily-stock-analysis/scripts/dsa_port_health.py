#!/usr/bin/env python3
"""
dsa_port_health.py — Batch DSA scan across all equity holdings.

Triggered by Hermes when user types:
  port health
  port-health
  持仓健康

Reads $PORTFOLIO_DIR/portfolio_truth.json (read-only),
filters to scannable equities (US/HK/JP stocks + ETFs; skips funds/bonds/cash),
runs the DSA dashboard on each, and emits a sorted summary + bearish detail
dashboards between __REPORT_START__/__REPORT_END__ markers on stdout — the
Hermes agent reads them and delivers over its own reply channel.

Output ordering: most-bearish first, then neutral, then bullish.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _dsa_lib import (  # noqa: E402
    call_llm_dashboard,
    emit_report,
    fetch_snapshot,
    format_dashboard,
    format_portfolio_summary,
    load_env,
    signal_severity,
)


PORTFOLIO_TRUTH = Path(os.environ.get("PORTFOLIO_DIR", str(Path.home() / ".hermes/profiles/aisa-cio/portfolio"))) / "portfolio_truth.json"


# ETF / common-equity Yahoo tickers we want to include
SCANNABLE_SUFFIXES = (".HK", ".T", ".SS", ".SZ", ".SI", ".KS")

# Tickers/ISINs that look like funds/bonds/cash and should be skipped
NON_EQUITY_PATTERNS = (
    "0P0",   # Yahoo's Lipper/Morningstar fund prefix
    "CODE:", # internal CODE: prefixes used by portfolio-truth-import
    "N/A",
)


def is_scannable(ticker: str | None) -> bool:
    """Heuristic: keep US tickers, HK/JP/SG/CN suffix tickers, common ETFs.
    Skip 0P0 fund codes, CODE: synthetic codes, OTC bonds.
    """
    if not ticker or not isinstance(ticker, str):
        return False
    t = ticker.strip()
    if not t:
        return False
    for bad in NON_EQUITY_PATTERNS:
        if bad in t.upper():
            return False
    # Has a suffix → keep (e.g. 0700.HK, 6758.T)
    if any(t.upper().endswith(suf.upper()) for suf in SCANNABLE_SUFFIXES):
        return True
    # No suffix and length 1-5 → assume US equity/ETF
    if 1 <= len(t) <= 5 and all(c.isalnum() or c in ".-" for c in t):
        return True
    return False


def load_holdings() -> list[dict]:
    """Load and filter portfolio_truth.json to scannable equities only.

    NEVER modifies the file. Returns a list of dicts with the keys:
      ticker, name, qty, cost_per_unit, cost_ccy
    """
    if not PORTFOLIO_TRUTH.exists():
        raise FileNotFoundError(f"portfolio_truth.json not found at {PORTFOLIO_TRUTH}")
    raw = json.loads(PORTFOLIO_TRUTH.read_text())
    if not isinstance(raw, list):
        raise ValueError("portfolio_truth.json is not a JSON array")

    out: list[dict] = []
    seen_tickers: set[str] = set()
    for entry in raw:
        ticker = entry.get("yahoo_ticker") or entry.get("ticker")
        if not is_scannable(ticker):
            continue
        # Dedup A/B lots of the same ticker (e.g. 0700.HK twice)
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)
        out.append({
            "ticker": ticker,
            "name": entry.get("name", ticker),
            "qty": entry.get("qty"),
            "cost_per_unit": entry.get("cost_per_unit"),
            "cost_ccy": entry.get("cost_ccy", "USD"),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="DSA batch scan of Hermes portfolio")
    ap.add_argument("--profile", default="fast_scan", choices=["fast_scan", "deep_research"])
    ap.add_argument("--limit", type=int, default=0,
                    help="Limit to first N tickers (0 = all). Useful for quick sanity test.")
    args = ap.parse_args()

    load_env()

    try:
        holdings = load_holdings()
    except Exception as e:
        emit_report(f"FAILED: cannot load holdings — {e}")
        return 1

    if args.limit > 0:
        holdings = holdings[: args.limit]

    print(f"[port-health] {len(holdings)} scannable equity tickers", file=sys.stderr)

    results: list[dict] = []
    failures: list[str] = []

    for h in holdings:
        ticker = h["ticker"]
        print(f"[port-health] {ticker} fetching…", file=sys.stderr)
        snap = fetch_snapshot(ticker)
        if not snap:
            failures.append(f"{ticker}: no data")
            continue

        # Override name from holdings (more recognizable than yfinance's longName for HK/JP)
        snap.name = h.get("name") or snap.name

        t0 = time.time()
        data = call_llm_dashboard(snap, profile=args.profile)
        elapsed = time.time() - t0
        if not data:
            failures.append(f"{ticker}: LLM failed")
            continue
        results.append(data)
        print(f"[port-health] {ticker} ✓ {elapsed:.1f}s "
              f"signal={data.get('core_conclusion',{}).get('signal','?')}",
              file=sys.stderr)

    if not results:
        emit_report(f"FAILED: 0 successful scans, {len(failures)} failures — {'; '.join(failures)}")
        return 1

    # 1) Summary (sorted by severity)
    summary = format_portfolio_summary(results)

    # 2) Individual detail dashboards — only for negative signals (focus user attention)
    details: list[str] = []
    for r in results:
        sig = (r.get("core_conclusion") or {}).get("signal", "Watch")
        if signal_severity(sig) >= 0:
            continue  # neutral/bullish — skip detail to avoid spam
        details.append(format_dashboard(r))

    print(f"[port-health] {len(details)} detail dashboards for bearish/alerts", file=sys.stderr)

    status = (f"DONE: scanned {len(results)}/{len(holdings)} "
              f"(bearish_details={len(details)}, failures={len(failures)})")
    if failures:
        status += f"\nFailures: {'; '.join(failures)}"
    emit_report("\n\n---\n\n".join([summary] + details + [status]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
