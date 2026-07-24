#!/usr/bin/env python3
"""
portfolio_report.py — Hermes Portfolio Reporter
Reads from portfolio_truth.json + portfolio_rules.json.
Fetches live prices + FX rates from Yahoo Finance.
Output format matches openclaw/PM exactly.

Usage: python3 portfolio_report.py
"""

import urllib.request, re, gzip, json, time, os
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT       = Path(__file__).resolve().parent
TRUTH_PATH = ROOT / "portfolio_truth.json"
RULES_PATH = ROOT / "portfolio_rules.json"

# FX fallback defaults — overridden at runtime by fetch_fx_rates()
HKD_USD = 0.1285
JPY_USD = 0.006878
SGD_USD = 0.744

_FX_TICKERS = {'HKD_USD': 'HKDUSD=X', 'JPY_USD': 'JPYUSD=X', 'SGD_USD': 'SGDUSD=X'}

BASELINE_USD = int(os.environ.get("PORTFOLIO_BASELINE_USD", "0"))   # 0 = hide baseline diff


# ─── Data loaders ─────────────────────────────────────────────────────────────

def load_truth():
    with TRUTH_PATH.open() as f:
        return json.load(f)

def load_rules():
    with RULES_PATH.open() as f:
        return json.load(f)


# ─── Yahoo quote fetcher (ported from openclaw portfolio_report.py) ────────────

def get_quote(symbol):
    url = f'https://finance.yahoo.com/quote/{symbol}/'
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html',
        'Accept-Encoding': 'gzip, deflate',
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            enc = r.headers.get('Content-Encoding', '')
            raw = r.read()
            html = (gzip.decompress(raw) if enc == 'gzip' else raw).decode('utf-8', errors='replace')
        for block in re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL):
            if 'quoteResponse' not in block:
                continue
            try:
                outer = json.loads(block)
                body  = outer.get('body', '')
                if not body: continue
                inner = json.loads(body) if isinstance(body, str) else body
                for item in inner.get('quoteResponse', {}).get('result', []):
                    if item.get('symbol') == symbol:
                        return item
            except Exception:
                pass
    except Exception:
        pass
    return None

def fetch_prices(tickers):
    """Fetch quotes for a deduplicated list of tickers; return {ticker: quote}."""
    quotes = {}
    for ticker in dict.fromkeys(tickers):
        quotes[ticker] = get_quote(ticker)
        time.sleep(0.35)
    return quotes

def fetch_fx_rates():
    """Fetch live FX from Yahoo. Returns dict with available keys."""
    rates = {}
    for var, ticker in _FX_TICKERS.items():
        q = get_quote(ticker)
        if q:
            p = q.get('regularMarketPrice', {})
            price = p.get('raw', 0) if isinstance(p, dict) else float(p or 0)
            if price > 0:
                rates[var] = price
        time.sleep(0.3)
    return rates


# ─── Helpers ──────────────────────────────────────────────────────────────────

def to_usd(value, ccy):
    if ccy == 'USD': return value
    if ccy == 'HKD': return value * HKD_USD
    if ccy == 'JPY': return value * JPY_USD
    if ccy == 'SGD': return value * SGD_USD
    return value

def pnl_emoji(pnl):
    if pnl > 0: return '🟢'
    if pnl < 0: return '🔴'
    return '⚪'

def fmt_price(price, ccy):
    if ccy == 'JPY': return f'JPY {price:,.0f}'
    if ccy == 'HKD': return f'HKD {price:.3f}'
    if ccy == 'SGD': return f'SGD {price:.4f}'
    return f'${price:.2f}'

def qty_str(qty):
    return f'{qty:,.0f}' if qty == int(qty) else f'{qty:,.2f}'

def classify(pos, rules):
    """Return section key: us / hk / jp_equity / jp_fund / fixed_income / sg_fund / cash / private."""
    isin   = pos.get('isin') or ''
    ticker = pos.get('yahoo_ticker') or ''

    # Explicit overrides from rules (e.g. a structured note → us)
    overrides = rules.get('classification_overrides', {})
    if isin in overrides and overrides[isin] == 'US_EQUITY':
        return 'us'

    if isin.startswith('CODE:'):
        return 'private' if ('PRIVATEBIZ' in isin or 'PRIVATEFUND' in isin) else 'cash'

    if not ticker:
        return 'fixed_income'   # bond (no ticker)

    if ticker.endswith('.HK'):
        return 'hk'
    if ticker.endswith('.T'):
        return 'jp_fund' if ticker.startswith('0P') else 'jp_equity'

    # ISIN-based for funds
    if isin.startswith('IE'):
        return 'fixed_income'   # e.g. Irish-domiciled bond fund
    if isin.startswith('SG'):
        return 'sg_fund'        # e.g. Singapore-domiciled fund

    if ticker.endswith('.SI'):
        return 'sg_fund'

    return 'us'


# ─── Report generator ─────────────────────────────────────────────────────────

def generate_report():
    global HKD_USD, JPY_USD, SGD_USD

    positions = load_truth()
    rules     = load_rules()

    # ── Live FX (ported from openclaw fetch_fx_rates) ──
    live_fx = fetch_fx_rates()
    HKD_USD = live_fx.get('HKD_USD', HKD_USD)
    JPY_USD = live_fx.get('JPY_USD', JPY_USD)
    SGD_USD = live_fx.get('SGD_USD', SGD_USD)
    fx_src  = 'live' if live_fx else 'fixed (fallback)'

    # JP Margin Loan from rules
    jp_margin_loan_usd = sum(
        lib['amount'] * JPY_USD if lib['ccy'] == 'JPY' else lib['amount']
        for lib in rules.get('liabilities', [])
    )

    # Classify positions
    by_cat = {k: [] for k in ('us', 'hk', 'jp_equity', 'jp_fund',
                               'fixed_income', 'sg_fund', 'cash', 'private')}
    for pos in positions:
        by_cat[classify(pos, rules)].append(pos)

    # Pre-fetch all live prices in one pass
    live_tickers = [
        p['yahoo_ticker'] for p in positions
        if p.get('yahoo_ticker') and not (p.get('isin') or '').startswith('CODE:')
    ]
    quotes = fetch_prices(live_tickers)

    sgt   = datetime.now(timezone(timedelta(hours=8)))
    lines = []
    lines.append(f"📅 *{sgt.strftime('%d %b %Y · %H:%M SGT')}*\n")
    lines.append(
        f"💱 FX ({fx_src}): "
        f"HKD {HKD_USD:.4f} · JPY {JPY_USD:.6f} · SGD {SGD_USD:.4f}\n"
    )

    grand_total_usd = 0.0
    gold_total_usd  = 0.0

    # ── Inline helper ─────────────────────────────────────────────────────────
    def render_equity(label, name, qty, cost, ccy, price, chg, section_totals):
        mkt   = to_usd(price * qty, ccy)
        base  = to_usd(cost  * qty, ccy)
        pnl   = mkt - base
        pct   = pnl / base * 100 if base else 0
        e     = pnl_emoji(pnl)
        lines.append(f"{e} *{label}* {name}")
        lines.append(f"Price {fmt_price(price, ccy)} · {chg:+.2f}%")
        lines.append(f"Qty {qty_str(qty)} sh · Cost {fmt_price(cost, ccy)}")
        lines.append(f"Value *${mkt:,.0f}* · PnL {e} {'+' if pnl>=0 else ''}${pnl:,.0f} *({pct:+.1f}%)*\n")
        section_totals.append((mkt, base))

    # ── US ────────────────────────────────────────────────────────────────────
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("🇺🇸 *US Equities & ETFs*")
    lines.append("━━━━━━━━━━━━━━━━━━━━\n")
    us_t = []
    for pos in by_cat['us']:
        isin, ticker, name = pos.get('isin') or '', pos.get('yahoo_ticker') or '', pos['name']
        qty  = float(pos['qty']);  cost = float(pos['cost_per_unit']);  ccy = pos['cost_ccy']

        if isin.startswith('CODE:'):   # structured note — static valuation
            val = qty
            lines.append("⚪ *Structured Note*")
            lines.append(f"Value *${val:,.0f}* · PnL ⚪ ~$0 (~0%)\n")
            us_t.append((val, val))
            continue

        q     = quotes.get(ticker)
        price = q.get('regularMarketPrice', {}).get('raw', cost) if q else cost
        chg   = q.get('regularMarketChangePercent', {}).get('raw', 0) if q else 0
        render_equity(ticker, name, qty, cost, ccy, price, chg, us_t)
        if ticker == 'IAU':
            gold_total_usd = to_usd(price * qty, ccy)

    us_val, us_cost = sum(v for v,_ in us_t), sum(c for _,c in us_t)
    us_pnl = us_val - us_cost
    e = pnl_emoji(us_pnl)
    lines.append(f"*US subtotal: ${us_val:,.0f} · {e} {'+' if us_pnl>=0 else ''}${us_pnl:,.0f} ({(us_pnl/us_cost*100 if us_cost else 0):+.1f}%)*")
    grand_total_usd += us_val

    # ── HK ────────────────────────────────────────────────────────────────────
    lines.append("\n━━━━━━━━━━━━━━━━━━━━")
    lines.append("🇭🇰 *HK Equities* (last close)")
    lines.append("━━━━━━━━━━━━━━━━━━━━\n")
    hk_t = []
    for pos in by_cat['hk']:
        ticker, name = pos['yahoo_ticker'], pos['name']
        qty, cost, ccy = float(pos['qty']), float(pos['cost_per_unit']), pos['cost_ccy']
        q     = quotes.get(ticker)
        price = q.get('regularMarketPrice', {}).get('raw', cost) if q else cost
        chg   = q.get('regularMarketChangePercent', {}).get('raw', 0) if q else 0
        render_equity(ticker.replace('.HK', ''), name, qty, cost, ccy, price, chg, hk_t)

    hk_val, hk_cost = sum(v for v,_ in hk_t), sum(c for _,c in hk_t)
    hk_pnl = hk_val - hk_cost
    e = pnl_emoji(hk_pnl)
    lines.append(f"*HK subtotal: ${hk_val:,.0f} · {e} {'+' if hk_pnl>=0 else ''}${hk_pnl:,.0f} ({(hk_pnl/hk_cost*100 if hk_cost else 0):+.1f}%)*")
    grand_total_usd += hk_val

    # ── JP Stocks + Fund ──────────────────────────────────────────────────────
    lines.append("\n━━━━━━━━━━━━━━━━━━━━")
    lines.append("🇯🇵 *Japan Equities* (after close)")
    lines.append("━━━━━━━━━━━━━━━━━━━━\n")
    jp_t = []
    for pos in by_cat['jp_equity']:
        ticker, name = pos['yahoo_ticker'], pos['name']
        qty, cost, ccy = float(pos['qty']), float(pos['cost_per_unit']), pos['cost_ccy']
        q     = quotes.get(ticker)
        price = q.get('regularMarketPrice', {}).get('raw', cost) if q else cost
        chg   = q.get('regularMarketChangePercent', {}).get('raw', 0) if q else 0
        render_equity(ticker.replace('.T', ''), name, qty, cost, ccy, price, chg, jp_t)

    for pos in by_cat['jp_fund']:   # JP mutual funds
        ticker, name = pos['yahoo_ticker'], pos['name']
        qty, cost, ccy = float(pos['qty']), float(pos['cost_per_unit']), pos['cost_ccy']
        q     = quotes.get(ticker)
        price = q.get('regularMarketPrice', {}).get('raw', cost) if q else cost
        chg   = q.get('regularMarketChangePercent', {}).get('raw', 0) if q else 0
        mkt   = to_usd(price * qty, ccy);  base = to_usd(cost * qty, ccy)
        pnl   = mkt - base;  pct = pnl / base * 100 if base else 0
        e     = pnl_emoji(pnl)
        lines.append(f"{e} *{name}*")
        lines.append(f"Price JPY {price:,.0f}/unit · {chg:+.2f}%")
        lines.append(f"Qty {qty_str(qty)} units · Cost JPY {cost:,.0f}")
        lines.append(f"Value *${mkt:,.0f}* · PnL {e} {'+' if pnl>=0 else ''}${pnl:,.0f} *({pct:+.1f}%)*\n")
        jp_t.append((mkt, base))

    jp_gross = sum(v for v,_ in jp_t);  jp_cost = sum(c for _,c in jp_t)
    jp_pnl   = jp_gross - jp_cost;      jp_net  = jp_gross - jp_margin_loan_usd
    e = pnl_emoji(jp_pnl)
    lines.append(f"Gross ${jp_gross:,.0f} · margin loan -${jp_margin_loan_usd:,.0f}")
    lines.append(f"*Japan net: ${jp_net:,.0f} · {e} {'+' if jp_pnl>=0 else ''}${jp_pnl:,.0f} ({(jp_pnl/jp_cost*100 if jp_cost else 0):+.1f}%)*")
    grand_total_usd += jp_net

    # ── Fixed Income ──────────────────────────────────────────────────────────
    lines.append("\n━━━━━━━━━━━━━━━━━━━━")
    lines.append("🏦 *Fixed Income*")
    lines.append("━━━━━━━━━━━━━━━━━━━━\n")
    fi_t = []
    for pos in by_cat['fixed_income']:
        isin, ticker, name = pos.get('isin') or '', pos.get('yahoo_ticker'), pos['name']
        qty, cost, ccy = float(pos['qty']), float(pos['cost_per_unit']), pos['cost_ccy']

        if not ticker:   # bond, no ticker — static at cost
            val = to_usd(cost * qty, ccy)
            lines.append(f"⚪ *{name}* `{isin}`")
            lines.append("Price static valuation (OTC, no live price)")
            lines.append(f"Qty {qty_str(qty)} units · Cost ${cost:.2f}")
            lines.append(f"Value *${val:,.0f}* · PnL ⚪ ~$0 (~0%)\n")
            fi_t.append((val, val))
            continue

        q     = quotes.get(ticker)
        price = q.get('regularMarketPrice', {}).get('raw', cost) if q else cost
        chg   = q.get('regularMarketChangePercent', {}).get('raw', 0) if q else 0
        mkt   = to_usd(price * qty, ccy);  base = to_usd(cost * qty, ccy)
        pnl   = mkt - base;  pct = pnl / base * 100 if base else 0
        e     = pnl_emoji(pnl)
        lines.append(f"{e} *{name}* `{isin}`")
        lines.append(f"Price {fmt_price(price, ccy)} · {chg:+.2f}%")
        lines.append(f"Qty {qty_str(qty)} units · Cost {fmt_price(cost, ccy)}")
        lines.append(f"Value *${mkt:,.0f}* · PnL {e} {'+' if pnl>=0 else ''}${pnl:,.0f} *({pct:+.1f}%)*\n")
        fi_t.append((mkt, base))

    fi_val, fi_cost = sum(v for v,_ in fi_t), sum(c for _,c in fi_t)
    fi_pnl = fi_val - fi_cost
    e = pnl_emoji(fi_pnl)
    lines.append(f"*Fixed Income subtotal: ${fi_val:,.0f} · {e} {'+' if fi_pnl>=0 else ''}${fi_pnl:,.0f} ({(fi_pnl/fi_cost*100 if fi_cost else 0):+.1f}%)*")
    grand_total_usd += fi_val

    # ── SG Funds ──────────────────────────────────────────────────────────────
    lines.append("\n━━━━━━━━━━━━━━━━━━━━")
    lines.append("🇸🇬 *Singapore Funds*")
    lines.append("━━━━━━━━━━━━━━━━━━━━\n")
    sg_t = []
    for pos in by_cat['sg_fund']:
        isin, ticker, name = pos.get('isin') or '', pos['yahoo_ticker'], pos['name']
        qty, cost, ccy = float(pos['qty']), float(pos['cost_per_unit']), pos['cost_ccy']
        q     = quotes.get(ticker)
        price = q.get('regularMarketPrice', {}).get('raw', cost) if q else cost
        chg   = q.get('regularMarketChangePercent', {}).get('raw', 0) if q else 0
        mkt   = to_usd(price * qty, ccy);  base = to_usd(cost * qty, ccy)
        pnl   = mkt - base;  pct = pnl / base * 100 if base else 0
        e     = pnl_emoji(pnl)
        lines.append(f"{e} *{name}* `{isin}`")
        lines.append(f"Price SGD {price:.4f} · {chg:+.2f}%")
        lines.append(f"Qty {qty_str(qty)} units · Cost SGD {cost:.4f}")
        lines.append(f"Value *${mkt:,.0f}* · PnL {e} {'+' if pnl>=0 else ''}${pnl:,.0f} *({pct:+.1f}%)*\n")
        sg_t.append((mkt, base))

    sg_val, sg_cost = sum(v for v,_ in sg_t), sum(c for _,c in sg_t)
    sg_pnl = sg_val - sg_cost
    e = pnl_emoji(sg_pnl)
    lines.append(f"*SG Funds subtotal: ${sg_val:,.0f} · {e} {'+' if sg_pnl>=0 else ''}${sg_pnl:,.0f} ({(sg_pnl/sg_cost*100 if sg_cost else 0):+.1f}%)*")
    grand_total_usd += sg_val

    # ── Cash ──────────────────────────────────────────────────────────────────
    cash_usd = 0.0
    cash_line = {}   # ordered display items
    for pos in by_cat['cash']:
        isin = pos.get('isin') or ''
        qty  = float(pos['qty'])
        ccy  = pos['cost_ccy']
        if 'CASH-USD' in isin:
            cash_line['Cash USD'] = qty;   cash_usd += qty
        elif 'MMF-USD' in isin:
            cash_line['MMF USD']  = qty;   cash_usd += qty
        elif 'MMF2' in isin:
            cash_line['MMF2']     = qty;   cash_usd += qty
        elif 'CASH-SGD' in isin:
            sgd_val = round(qty * SGD_USD)
            cash_line['Cash SGD'] = sgd_val
            cash_usd += sgd_val

    lines.append("\n━━━━━━━━━━━━━━━━━━━━")
    lines.append("💵 *Cash*")
    lines.append("━━━━━━━━━━━━━━━━━━━━\n")
    for label in ('Cash USD', 'MMF USD', 'MMF2', 'Cash SGD'):
        if label in cash_line:
            lines.append(f"{label} · *${cash_line[label]:,.0f}*")
    lines.append(f"\n*Cash subtotal: ~${cash_usd:,.0f}*")
    grand_total_usd += cash_usd

    # ── Private ───────────────────────────────────────────────────────────────
    private_usd = 0.0
    lines.append("\n━━━━━━━━━━━━━━━━━━━━")
    lines.append("🏠 *Private & Alternatives*")
    lines.append("━━━━━━━━━━━━━━━━━━━━\n")
    for pos in by_cat['private']:
        name = pos['name'];  qty = float(pos['qty']);  ccy = pos['cost_ccy']
        val  = to_usd(qty, ccy)
        lines.append(f"{name} · *${val:,.0f}*")
        private_usd += val
    lines.append(f"\n*Private subtotal: ~${private_usd:,.0f}*")
    grand_total_usd += private_usd

    # ── Summary ───────────────────────────────────────────────────────────────
    lines.append("\n━━━━━━━━━━━━━━━━━━━━")
    lines.append("📊 *Asset Allocation Overview*")
    lines.append("━━━━━━━━━━━━━━━━━━━━\n")
    diff = grand_total_usd - BASELINE_USD
    e    = pnl_emoji(diff)
    alloc = [
        ("🥇 Gold",          gold_total_usd),
        ("🇺🇸 US Equities",   us_val - gold_total_usd),
        ("🇭🇰 HK Equities",   hk_val),
        ("🇯🇵 Japan (net)",   jp_net),
        ("🏦 Fixed Income",   fi_val),
        ("🇸🇬 SG Funds",      sg_val),
        ("💵 Cash",           cash_usd),
        ("🏠 Private",        private_usd),
    ]
    for label, val in alloc:
        pct = val / grand_total_usd * 100 if grand_total_usd else 0
        lines.append(f"{label}: ${val:,.0f} ({pct:.1f}%)")
    lines.append("────────────────────────")
    lines.append(f"*Total net worth: ~${grand_total_usd:,.0f}*")
    if BASELINE_USD > 0:
        lines.append(f"Baseline: ${BASELINE_USD:,.0f}")
        lines.append(f"*Total change: {e} {'+' if diff>=0 else ''}${diff:,.0f} ({diff/BASELINE_USD*100:+.1f}%)*")

    return '\n'.join(lines)


if __name__ == '__main__':
    import hashlib as _h, json as _j, os as _os
    _report = generate_report()
    # Data-source sentinel (anti-fabrication): emitted OUTSIDE the narrative so
    # the on-demand skill can validate the model actually ran the script.
    try:
        _truth_path = str(TRUTH_PATH.resolve())
        _truth = load_truth()
        _holdings_n = len(_truth) if isinstance(_truth, list) else len(_truth.get('items', []))
        _mtime = int(_os.path.getmtime(TRUTH_PATH))
        _digest = _h.md5(_j.dumps(_truth, sort_keys=True).encode()).hexdigest()[:10]
        print(f'__DATA_SOURCE__: path={_truth_path} holdings={_holdings_n} mtime={_mtime} md5={_digest}')
    except Exception as _e:
        print(f'__DATA_SOURCE__: ERROR {type(_e).__name__}: {_e}')
    print(_report)

