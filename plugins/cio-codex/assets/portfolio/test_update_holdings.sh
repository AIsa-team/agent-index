#!/usr/bin/env bash
# test_update_holdings.sh — CLI regression tests for update_holdings.py.
# Runs against a throwaway fixture in a tmpdir; never touches real truth.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

setup() {
  rm -rf "$TMP"/*
  cp "$HERE/update_holdings.py" "$TMP/"
  cat > "$TMP/portfolio_truth.json" <<'EOF'
[
  {"isin": null, "name": "NVIDIA Corp", "yahoo_ticker": "NVDA",
   "qty": 100, "cost_per_unit": 100.0, "cost_ccy": "USD",
   "meta": {"preferred_symbol": "NVDA"}},
  {"isin": null, "name": "Tencent A", "yahoo_ticker": "0700.HK",
   "qty": 200, "cost_per_unit": 300.0, "cost_ccy": "HKD",
   "meta": {"preferred_symbol": "0700.HK"}},
  {"isin": null, "name": "Tencent B", "yahoo_ticker": "0700.HK",
   "qty": 100, "cost_per_unit": 400.0, "cost_ccy": "HKD",
   "meta": {"preferred_symbol": "0700.HK"}},
  {"isin": "CODE:MMF-USD", "name": "MMF USD", "yahoo_ticker": null,
   "qty": 300000, "cost_per_unit": 1, "cost_ccy": "USD",
   "meta": {"preferred_symbol": null}}
]
EOF
}

run_uh() { (cd "$TMP" && python3 update_holdings.py "$@") ; }

check() {  # check NAME EXPECTED_RC GREP_PATTERN -- ARGS...
  local name="$1" want_rc="$2" pat="$3"; shift 3; [ "$1" = "--" ] && shift
  out=$(run_uh "$@" 2>&1); rc=$?
  if [ "$rc" -eq "$want_rc" ] && echo "$out" | grep -q "$pat"; then
    printf "[PASS] %s\n" "$name"; PASS=$((PASS+1))
  else
    printf "[FAIL] %s (rc=%s want=%s)\n---\n%s\n---\n" "$name" "$rc" "$want_rc" "$out"
    FAIL=$((FAIL+1))
  fi
}

# ── T1 snapshot: any write creates snapshots/<ts>_portfolio_truth.json ──
setup
check "T1a buy prints snapshot line" 0 "snapshot:" -- buy NVDA 50 120
t1b() {
  n=$(ls "$TMP"/snapshots/*_portfolio_truth.json 2>/dev/null | wc -l | tr -d ' ')
  [ "$n" = "1" ]
}
if t1b; then printf "[PASS] T1b snapshot file exists\n"; PASS=$((PASS+1))
else printf "[FAIL] T1b snapshot file exists\n"; FAIL=$((FAIL+1)); fi

# ── T2 list ──
setup
check "T2a list shows NVDA row" 0 "NVDA" -- list
check "T2b list shows index"    0 "\[ 0\]" -- list

# ── T3 add ──
setup
check "T3a add new HK ticker infers HKD" 0 "HKD" -- add 9988.HK 300 80
check "T3b added row visible in list"    0 "9988.HK" -- list
check "T3c add duplicate rejected"       1 "already exists" -- add NVDA 1 1
setup
check "T3d add --name --ccy override" 0 "SPY500" -- add SPY 10 500 --name SPY500 --ccy USD
check "T3e add mentions pending isin" 0 "pending" -- add TSLA 10 200

# ── T4 remove ──
setup
check "T4a remove single-lot ticker"      0 "REMOVED" -- remove NVDA
check "T4b removed row gone from list"    0 "MMF" -- list   # sanity: file still valid
t4c() { run_uh list | grep -q "NVDA"; }   # NVDA must be gone
if t4c; then printf "[FAIL] T4c NVDA still present\n"; FAIL=$((FAIL+1))
else printf "[PASS] T4c NVDA row deleted\n"; PASS=$((PASS+1)); fi
setup
check "T4d remove multi-lot needs --lot"  1 "specify --lot" -- remove 0700.HK
check "T4e remove multi-lot with --lot"   0 "REMOVED" -- remove 0700.HK --lot 2
check "T4f remove bad --lot rejected"     1 "not a lot" -- remove 0700.HK --lot 3

# ── T5 --lot on buy/sell/set ──
setup
check "T5a buy into lot 2"  0 "500" -- buy 0700.HK 100 500 --lot 2
check "T5b sell from lot 1" 0 "SELL" -- sell 0700.HK 50 --lot 1
check "T5c set qty on lot 2" 0 "SET qty" -- set 0700.HK qty 150 --lot 2
check "T5d bad lot rejected" 1 "not a lot" -- buy 0700.HK 1 1 --lot 0

# ── T6 sell-to-zero hint ──
setup
check "T6a full exit suggests remove" 0 "remove NVDA" -- sell NVDA 100

printf "\n%d passed, %d failed\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
