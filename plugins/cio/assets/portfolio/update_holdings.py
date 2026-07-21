#!/usr/bin/env python3
"""
update_holdings.py — Hermes Portfolio Holdings Updater
Atomically updates portfolio_truth.json.

Usage:
  python3 update_holdings.py buy   TICKER QTY PRICE       # add to position (weighted avg cost)
  python3 update_holdings.py sell  TICKER QTY             # reduce position (cost unchanged)
  python3 update_holdings.py set   TICKER cost PRICE      # override unit cost basis
  python3 update_holdings.py set   TICKER qty  QTY        # override quantity
  python3 update_holdings.py set   NAME   value AMOUNT    # set cash/static item value
  python3 update_holdings.py add    TICKER QTY PRICE [--name NAME] [--ccy CCY]  # new position
  python3 update_holdings.py remove TICKER [--lot INDEX]                        # delete a row
  python3 update_holdings.py list                                               # show all rows

TICKER examples : NVDA, 0700.HK, 7203.T
NAME examples   : Cash, MMF, MMF2, PrivateFund, PrivateBiz, StructNote

Examples:
  python3 update_holdings.py buy  NVDA 100 200.50
  python3 update_holdings.py buy  0700.HK 200 380.00
  python3 update_holdings.py sell MSFT 50
  python3 update_holdings.py set  MSFT cost 350.00
  python3 update_holdings.py set  NVDA qty  900
  python3 update_holdings.py set  MMF  value 350000
  python3 update_holdings.py set  PrivateFund  value 100000
"""

import json, sys, re, shutil
from datetime import date, datetime
from pathlib import Path

TRUTH_PATH = Path(__file__).resolve().parent / "portfolio_truth.json"
SNAP_DIR = TRUTH_PATH.parent / "snapshots"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def fmt(n) -> str:
    """Minimal decimal string — no trailing zeros."""
    if n == int(n):
        return str(int(n))
    return f"{n:.8f}".rstrip('0').rstrip('.')

def infer_ccy(ticker: str) -> str:
    t = ticker.upper()
    if t.endswith('.HK'): return 'HKD'
    if t.endswith('.T'):  return 'JPY'
    if t.endswith('.SI'): return 'SGD'
    return 'USD'

# Maps user-friendly cash names → CODE: ISIN fragment
CASH_ISIN_MAP = {
    'cash':       'CODE:CASH-USD',
    'cashusd':    'CODE:CASH-USD',
    'mmf':        'CODE:MMF-USD',
    'mmfusd':     'CODE:MMF-USD',
    'mmf2':       'CODE:MMF2',
    'mmf2fund':   'CODE:MMF2',
    'privatefund':'CODE:PRIVATEFUND',
    'privatebiz': 'CODE:PRIVATEBIZ',
    'structnote': 'CODE:STRUCTNOTE',
}


# ─── portfolio_truth.json I/O ─────────────────────────────────────────────────

def load() -> list:
    with TRUTH_PATH.open() as f:
        return json.load(f)

def snapshot() -> Path:
    """Copy current truth into snapshots/ before any write. Failure aborts the write."""
    SNAP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = SNAP_DIR / f"{ts}_portfolio_truth.json"
    shutil.copy2(TRUTH_PATH, dst)
    return dst

def save(positions: list):
    snap = snapshot()
    with TRUTH_PATH.open('w') as f:
        json.dump(positions, f, indent=2, ensure_ascii=False)
    print(f"📸 snapshot: {snap.name}")

def find_equity(positions, ticker: str) -> list[int]:
    """Return list of indices matching ticker (may be >1 for duplicate lots like a dual-listed ETF)."""
    t = ticker.upper()
    return [i for i, p in enumerate(positions)
            if (p.get('yahoo_ticker') or '').upper() == t]

def find_cash(positions, name_key: str) -> int | None:
    """Return index of cash/private item by CODE: ISIN."""
    target_isin = CASH_ISIN_MAP.get(name_key.lower().replace(' ', '').replace('_', ''))
    if not target_isin:
        return None
    for i, p in enumerate(positions):
        if p.get('isin') == target_isin:
            return i
    return None

def _pick_lot(positions, ticker: str, lot: int | None, verb: str) -> int:
    """Resolve which array index to operate on; exits with a message on error."""
    idxs = find_equity(positions, ticker)
    if not idxs:
        print(f"❌ '{ticker}' not found. Use 'add' to create a new position.")
        sys.exit(1)
    if lot is not None:
        if lot not in idxs:
            print(f"❌ --lot {lot} is not a lot of {ticker}. Lots: {idxs}")
            sys.exit(1)
        return lot
    if len(idxs) > 1:
        print(f"⚠️  Multiple lots found for {ticker}:")
        for i in idxs:
            p = positions[i]
            print(f"   [{i}] {p['name']}  qty={fmt(float(p['qty']))}  "
                  f"cost={fmt(float(p['cost_per_unit']))}  {p['cost_ccy']}")
        print(f"   {verb} defaulting to first lot [{idxs[0]}]. Use --lot INDEX to target another.")
    return idxs[0]


# ─── Operations ───────────────────────────────────────────────────────────────

def op_buy(ticker: str, qty: float, price: float, lot: int | None = None):
    positions = load()
    idx = _pick_lot(positions, ticker, lot, 'BUY')
    pos = positions[idx]
    old_qty  = float(pos['qty'])
    old_cost = float(pos['cost_per_unit'])
    new_qty  = old_qty + qty
    new_cost = (old_qty * old_cost + qty * price) / new_qty
    ccy = pos['cost_ccy']

    positions[idx]['qty']           = new_qty
    positions[idx]['cost_per_unit'] = new_cost
    save(positions)
    print(f"✅ {ticker} — BUY {fmt(qty)} @ {ccy} {fmt(price)}")
    print(f"   Before : {fmt(old_qty)} @ {ccy} {fmt(old_cost)}")
    print(f"   After  : {fmt(new_qty)} @ {ccy} {fmt(new_cost)}  (weighted avg)")

def op_sell(ticker: str, qty: float, lot: int | None = None):
    positions = load()
    idx = _pick_lot(positions, ticker, lot, 'SELL')
    pos = positions[idx]
    old_qty  = float(pos['qty'])
    old_cost = float(pos['cost_per_unit'])
    ccy = pos['cost_ccy']
    if qty > old_qty:
        print(f"❌ Cannot sell {fmt(qty)} — only {fmt(old_qty)} held."); sys.exit(1)
    new_qty = old_qty - qty
    if new_qty == 0:
        positions[idx]['qty'] = 0
        save(positions)
        print(f"✅ {ticker} — SELL {fmt(qty)} (full exit, qty now 0)")
        print(f"   Row kept with qty=0. To delete it run: update_holdings.py remove {ticker}")
        sys.exit(0)
    positions[idx]['qty'] = new_qty
    save(positions)
    print(f"✅ {ticker} — SELL {fmt(qty)}")
    print(f"   Before : {fmt(old_qty)} @ {ccy} {fmt(old_cost)}")
    print(f"   After  : {fmt(new_qty)} @ {ccy} {fmt(old_cost)}  (cost unchanged)")

def op_set_cost(ticker: str, new_cost: float, lot: int | None = None):
    positions = load()
    idx = _pick_lot(positions, ticker, lot, 'SET')
    old_cost = float(positions[idx]['cost_per_unit'])
    ccy = positions[idx]['cost_ccy']
    positions[idx]['cost_per_unit'] = new_cost
    save(positions)
    print(f"✅ {ticker} — SET cost {ccy} {fmt(old_cost)} → {fmt(new_cost)}")

def op_set_qty(ticker: str, new_qty: float, lot: int | None = None):
    positions = load()
    idx = _pick_lot(positions, ticker, lot, 'SET')
    old_qty = float(positions[idx]['qty'])
    positions[idx]['qty'] = new_qty
    save(positions)
    print(f"✅ {ticker} — SET qty {fmt(old_qty)} → {fmt(new_qty)}")

def op_set_value(item: str, new_value: float):
    """Update qty (= value) for a CODE: cash/static item."""
    positions = load()
    idx = find_cash(positions, item)
    if idx is None:
        key = item.lower().replace(' ', '').replace('_', '')
        if key not in CASH_ISIN_MAP:
            print(f"❌ Unknown item '{item}'.")
            print(f"   Known: Cash, MMF, MMF2, PrivateFund, PrivateBiz, StructNote")
        else:
            print(f"❌ '{item}' not found in portfolio_truth.json.")
        sys.exit(1)
    pos     = positions[idx]
    old_val = float(pos['qty'])
    ccy     = pos['cost_ccy']
    positions[idx]['qty'] = new_value
    save(positions)
    print(f"✅ {pos['name']} — SET value {fmt(old_val)} → {fmt(new_value)} {ccy}")

def op_list():
    positions = load()
    for i, p in enumerate(positions):
        tick = p.get('yahoo_ticker') or p.get('isin') or '—'
        print(f"[{i:>2}] {p['name']:<32} {tick:<16} "
              f"qty={fmt(float(p['qty'])):>14}  cost={fmt(float(p['cost_per_unit'])):>12}  {p['cost_ccy']}")

def op_add(ticker: str, qty: float, price: float, name: str | None, ccy: str | None):
    positions = load()
    if find_equity(positions, ticker):
        print(f"❌ '{ticker}' already exists — use 'buy' to add to the position.")
        sys.exit(1)
    ccy = (ccy or infer_ccy(ticker)).upper()
    row = {
        "isin": None,
        "name": name or ticker,
        "yahoo_ticker": ticker,
        "qty": qty,
        "cost_per_unit": price,
        "cost_ccy": ccy,
        "meta": {"preferred_symbol": ticker},
    }
    positions.append(row)
    save(positions)
    print(f"✅ {ticker} — ADD {fmt(qty)} @ {ccy} {fmt(price)}  ({row['name']})")
    print("   ISIN mapping: pending — run the symbol_map workflow later if needed.")

def op_remove(ticker: str, lot: int | None):
    positions = load()
    idxs = find_equity(positions, ticker)
    if not idxs:
        print(f"❌ '{ticker}' not found."); sys.exit(1)
    if len(idxs) > 1 and lot is None:
        print(f"⚠️  Multiple lots found for {ticker} — specify --lot INDEX:")
        for i in idxs:
            p = positions[i]
            print(f"   [{i}] {p['name']}  qty={fmt(float(p['qty']))}  "
                  f"cost={fmt(float(p['cost_per_unit']))}  {p['cost_ccy']}")
        sys.exit(1)
    idx = lot if lot is not None else idxs[0]
    if idx not in idxs:
        print(f"❌ --lot {idx} is not a lot of {ticker}. Lots: {idxs}"); sys.exit(1)
    print("Removing row:")
    print(json.dumps(positions[idx], indent=2, ensure_ascii=False))
    del positions[idx]
    save(positions)
    print(f"✅ {ticker} — REMOVED")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def pop_flag(args: list, flag: str) -> str | None:
    """Extract '--flag VALUE' from args in place; return VALUE or None."""
    if flag not in args:
        return None
    i = args.index(flag)
    if i + 1 >= len(args):
        print(f"❌ {flag} requires a value"); sys.exit(1)
    val = args[i + 1]
    del args[i:i + 2]
    return val

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    action = args[0].lower()

    name_flag = pop_flag(args, '--name')
    ccy_flag  = pop_flag(args, '--ccy')
    lot_raw = pop_flag(args, '--lot')
    lot = int(lot_raw) if lot_raw is not None else None

    if action == 'buy':
        if len(args) < 4:
            print("Usage: buy TICKER QTY PRICE"); sys.exit(1)
        op_buy(args[1].upper(), float(args[2]), float(args[3]), lot)

    elif action == 'sell':
        if len(args) < 3:
            print("Usage: sell TICKER QTY"); sys.exit(1)
        op_sell(args[1].upper(), float(args[2]), lot)

    elif action == 'set':
        if len(args) < 4:
            print("Usage: set TICKER|NAME cost|qty|value AMOUNT"); sys.exit(1)
        target = args[1]
        field  = args[2].lower()
        value  = float(args[3])
        if field == 'cost':
            op_set_cost(target.upper(), value, lot)
        elif field == 'qty':
            op_set_qty(target.upper(), value, lot)
        elif field == 'value':
            op_set_value(target, value)
        else:
            print(f"❌ Unknown field '{field}'. Use: cost, qty, value"); sys.exit(1)

    elif action == 'list':
        op_list()

    elif action == 'add':
        if len(args) < 4:
            print("Usage: add TICKER QTY PRICE [--name NAME] [--ccy CCY]"); sys.exit(1)
        op_add(args[1].upper(), float(args[2]), float(args[3]), name_flag, ccy_flag)

    elif action == 'remove':
        if len(args) < 2:
            print("Usage: remove TICKER [--lot INDEX]"); sys.exit(1)
        op_remove(args[1].upper(), lot)

    else:
        print(f"❌ Unknown action '{action}'. Use: buy, sell, set, add, remove, list")
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()
