#!/usr/bin/env python3
"""
valuation_push.py — Hermes /888 portfolio valuation push.
Reads portfolio_truth.json + portfolio_rules.json, fetches Yahoo prices in
parallel, outputs formatted report to stdout.
"""
from __future__ import annotations

import gzip
import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRUTH_PATH = ROOT / "portfolio_truth.json"
RULES_PATH = ROOT / "portfolio_rules.json"
SNAPSHOTS_DIR = ROOT / "snapshots"


def load_data():
    with TRUTH_PATH.open() as f:
        positions = json.load(f)
    with RULES_PATH.open() as f:
        rules = json.load(f)
    return positions, rules


def get_fx(rules):
    fx = rules.get("fx_overrides", {})
    return {
        "HKD": fx.get("HKDUSD", 0.1285),
        "JPY": fx.get("JPYUSD", 0.006878),
        "SGD": fx.get("SGDUSD", 0.744),
        "USD": 1.0,
        "as_of": fx.get("as_of", ""),
    }


def classify(pos, rules):
    isin = pos.get("isin") or ""
    ticker = pos.get("yahoo_ticker") or ""
    overrides = rules.get("classification_overrides", {})
    if isin in overrides:
        if overrides[isin] == "US_EQUITY":
            return "us"
    if isin.startswith("CODE:"):
        return "cash_private"
    if not ticker:
        return "fixed_income"
    if ticker.endswith(".HK"):
        return "hk"
    if ticker.endswith(".T"):
        return "jp_fund" if ticker.startswith("0P") else "jp_equity"
    if ticker.endswith(".SI") or ticker.startswith("0P"):
        return "sg_fund"
    return "us"


def fetch_yahoo(symbol: str):
    url = f"https://finance.yahoo.com/quote/{symbol}/"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html",
        "Accept-Encoding": "gzip, deflate",
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            enc = resp.headers.get("Content-Encoding", "")
            raw = resp.read()
            html = (gzip.decompress(raw) if enc == "gzip" else raw).decode("utf-8", errors="replace")
        for block in re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL):
            if "quoteResponse" not in block:
                continue
            try:
                outer = json.loads(block)
                body = outer.get("body", "")
                inner = json.loads(body) if isinstance(body, str) else body
                for item in inner.get("quoteResponse", {}).get("result", []):
                    if item.get("symbol") == symbol:
                        p = item.get("regularMarketPrice", {})
                        return float(p.get("raw", 0) if isinstance(p, dict) else p or 0) or None
            except Exception:
                continue
    except Exception:
        pass
    return None


def fetch_all_prices(tickers):
    results = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        future_to_ticker = {pool.submit(fetch_yahoo, t): t for t in tickers}
        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                results[ticker] = future.result()
            except Exception:
                results[ticker] = None
    return results


def to_usd(value, ccy, fx):
    return value * fx.get(ccy, 1.0)


def dot(pnl):
    if pnl > 0.5:
        return "🟢"
    if pnl < -0.5:
        return "🔴"
    return "⚪"


def fmt(v):
    return f"${v:,.0f}"


def generate_report():
    positions, rules = load_data()
    fx = get_fx(rules)

    safety_codes = set(rules.get("safety_ringfenced", []))
    mmf_codes = set(rules.get("mmf_codes", []))
    mmf_safety_limit = float(rules.get("mmf_safety_allocation_usd", 120000))
    liabilities = rules.get("liabilities", [])

    unique_tickers = list({p["yahoo_ticker"] for p in positions if p.get("yahoo_ticker")})
    prices = fetch_all_prices(unique_tickers)

    enriched = []
    for pos in positions:
        isin = pos.get("isin") or ""
        ticker = pos.get("yahoo_ticker")
        name = pos.get("name", "")
        qty = float(pos.get("qty", 0))
        cost_pu = float(pos.get("cost_per_unit", 0))
        ccy = pos.get("cost_ccy", "USD")
        cat = classify(pos, rules)

        is_static = isin.startswith("CODE:")
        is_at_cost = (not ticker and not is_static)

        if is_static:
            price = 1.0
            tag = "[static]"
        elif is_at_cost:
            price = cost_pu
            tag = "[at cost]"
        else:
            price = prices.get(ticker) or cost_pu
            tag = ""

        value_usd = to_usd(price * qty, ccy, fx)
        cost_usd = to_usd(cost_pu * qty, ccy, fx)
        pnl_usd = 0.0 if (is_static or is_at_cost) else value_usd - cost_usd

        enriched.append({
            "name": name, "ticker": ticker, "isin": isin,
            "qty": qty, "cost_pu": cost_pu, "ccy": ccy,
            "price": price, "value_usd": value_usd,
            "cost_usd": cost_usd, "pnl_usd": pnl_usd,
            "tag": tag, "is_static": is_static, "is_at_cost": is_at_cost,
            "cat": cat,
        })

    by_cat = {"us": [], "hk": [], "jp_equity": [], "jp_fund": [],
              "fixed_income": [], "sg_fund": [], "cash_private": []}
    for p in enriched:
        by_cat[p["cat"]].append(p)

    mmf_total = sum(p["value_usd"] for p in by_cat["cash_private"] if p["isin"] in mmf_codes)
    mmf_to_safety = min(mmf_total, mmf_safety_limit)
    mmf_investable = mmf_total - mmf_to_safety
    ringfenced_usd = sum(p["value_usd"] for p in by_cat["cash_private"] if p["isin"] in safety_codes)
    cash_usd = sum(p["value_usd"] for p in by_cat["cash_private"]
                   if p["isin"] not in mmf_codes and p["isin"] not in safety_codes)
    liabilities_usd = sum(to_usd(float(l["amount"]), l["ccy"], fx) for l in liabilities)

    def sec_val(cat):
        return sum(p["value_usd"] for p in by_cat[cat])

    investable = (sec_val("us") + sec_val("hk") + sec_val("jp_equity") +
                  sec_val("jp_fund") + sec_val("fixed_income") +
                  sec_val("sg_fund") + mmf_investable + cash_usd)
    safety_total = mmf_to_safety + ringfenced_usd
    net = investable + safety_total - liabilities_usd

    sgt = datetime.now(timezone(timedelta(hours=8)))
    lines = []
    lines.append(f"📅 {sgt.strftime('%d %b %Y · %H:%M SGT')}")
    lines.append(f"FX: HKDUSD {fx['HKD']} · JPYUSD {fx['JPY']} · SGDUSD {fx['SGD']} (as_of {fx['as_of']})")
    lines.append(f"MMF: {fmt(mmf_total)}  →  Safety {fmt(mmf_to_safety)}  Remainder {fmt(mmf_investable)}")
    lines.append(f"Safety: {fmt(safety_total)}  (ringfenced {fmt(ringfenced_usd)} + MMF {fmt(mmf_to_safety)})")
    lines.append(f"Investable: {fmt(investable)}  Net after liabilities: {fmt(net)}")
    lines.append("")

    def render_section(title, items, show_pnl=True):
        lines.append(title)
        sub_val = sub_pnl = 0.0
        ticker_count = {}
        for p in items:
            t = p["ticker"] or ""
            ticker_count[t] = ticker_count.get(t, 0) + 1

        for p in items:
            ticker = p["ticker"] or ""
            short = ticker.split(".")[0] if "." in ticker else ticker
            dup = ticker_count.get(ticker, 0) > 1
            if dup:
                label = f"{short} ({p['name']})"
            elif short and short != p["name"]:
                label = f"{short} {p['name']}"
            else:
                label = p["name"]

            parts = [f"{dot(p['pnl_usd'])} {label}  qty {p['qty']:,.2f}  value {fmt(p['value_usd'])}"]
            if show_pnl and not p["is_static"] and not p["is_at_cost"]:
                pnl_pct = (p["pnl_usd"] / p["cost_usd"] * 100) if p["cost_usd"] else 0
                sign = "+" if p["pnl_usd"] >= 0 else ""
                parts.append(f"PnL {fmt(p['pnl_usd'])} ({sign}{pnl_pct:.1f}%)")
            if p["tag"]:
                parts.append(p["tag"])
            lines.append("  ".join(parts))
            sub_val += p["value_usd"]
            sub_pnl += p["pnl_usd"]

        cost_base = sub_val - sub_pnl
        pnl_pct = (sub_pnl / cost_base * 100) if cost_base else 0
        sign = "+" if sub_pnl >= 0 else ""
        lines.append(f"Subtotal: {fmt(sub_val)}  PnL: {fmt(sub_pnl)} ({sign}{pnl_pct:.1f}%)")
        lines.append("")

    render_section("🇺🇸 US Equities & ETFs (USD)", by_cat["us"])
    render_section("🇭🇰 HK Equities (HKD)", by_cat["hk"])
    render_section("🇯🇵 Japan Equities (JPY)", by_cat["jp_equity"])
    render_section("🇯🇵 Japan Funds (JPY)", by_cat["jp_fund"])
    render_section("🏦 Fixed Income", by_cat["fixed_income"], show_pnl=False)
    render_section("🇸🇬 Singapore Funds (SGD)", by_cat["sg_fund"])

    lines.append("💵 Cash & Private")
    for p in by_cat["cash_private"]:
        if p["isin"] in safety_codes:
            alloc = "safety"
        elif p["isin"] in mmf_codes:
            alloc = "mmf"
        else:
            alloc = "cash"
        lines.append(f"⚪ {p['name']}  qty {p['qty']:,.0f}  value {fmt(p['value_usd'])}  {p['tag']}  [{alloc}]")
    lines.append(f"Subtotal: {fmt(sum(p['value_usd'] for p in by_cat['cash_private']))}")
    lines.append("")

    for l in liabilities:
        l_usd = to_usd(float(l["amount"]), l["ccy"], fx)
        lines.append(f"Liability  {l['name']}: {l['ccy']} {l['amount']:,.0f} ≈ {fmt(l_usd)}")
    lines.append("")
    lines.append(f"Net Portfolio Value: {fmt(net)}")

    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    snap = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fx": fx,
        "positions": [{"name": p["name"], "ticker": p["ticker"], "qty": p["qty"],
                       "price": p["price"], "value_usd": p["value_usd"],
                       "pnl_usd": p["pnl_usd"], "tag": p["tag"], "cat": p["cat"]}
                      for p in enriched],
        "mmf_total_usd": mmf_total, "mmf_to_safety_usd": mmf_to_safety,
        "safety_total_usd": safety_total, "investable_usd": investable,
        "liabilities_usd": liabilities_usd, "net_after_liabilities_usd": net,
    }
    snap_path = SNAPSHOTS_DIR / f"{ts}_valuation_alt.json"
    with snap_path.open("w") as f:
        json.dump(snap, f, indent=2)

    return "\n".join(lines)


if __name__ == "__main__":
    t0 = time.time()
    report = generate_report()
    elapsed = time.time() - t0
    print(report)
    print(f"\n(generated in {elapsed:.1f}s)")
