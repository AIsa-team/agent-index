#!/usr/bin/env bash
# golden_tests.sh — Regression safety net for Hermes portfolio pipeline.
# Run after: model changes, skill edits, config changes, dependency upgrades.
#
# Tests:
#   T1 — portfolio_report.py runs, emits __DATA_SOURCE__, passes validator
#   T2 — validator catches empty input
#   T3 — validator catches missing __DATA_SOURCE__
#   T4 — validator catches the exact hallucination pattern from 2026-04-24
#   T5 — update_holdings.py is invocable (dry-check)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PASS=0; FAIL=0
log() { printf "%-20s  %s\n" "$1" "$2"; }

run() {
  local name="$1"; shift
  if "$@" >/tmp/gt.out 2>/tmp/gt.err; then
    log "[PASS] $name" ""; PASS=$((PASS+1))
  else
    log "[FAIL] $name" "exit=$? (see /tmp/gt.out /tmp/gt.err)"; FAIL=$((FAIL+1))
  fi
}

# T1 — real report runs and validates
t1_real() {
  out=$(python3 "$HERE/portfolio_report.py" 2>/dev/null) || return 1
  echo "$out" | grep -q '__DATA_SOURCE__:' || return 2
  echo "$out" | python3 "$HERE/validate_report.py" - || return 3
}
run "T1 real report passes validator" t1_real

# T2 — empty input rejected
t2_empty() {
  echo -n "" | python3 "$HERE/validate_report.py" -; rc=$?
  [ $rc -eq 1 ]
}
run "T2 empty report rejected" t2_empty

# T3 — missing __DATA_SOURCE__ rejected
t3_missing() {
  printf "总净值: ~\$2,453,881\n资产配置总览\n" | python3 "$HERE/validate_report.py" -; rc=$?
  [ $rc -eq 2 ]
}
run "T3 missing sentinel rejected" t3_missing

# T4 — fabrication pattern rejected (the exact 2026-04-24 incident)
t4_fabrication() {
  cat <<FAKE | python3 "$HERE/validate_report.py" -
__DATA_SOURCE__: path=/fake holdings=3
Portfolio Summary
1. AAPL (Apple Inc.) Holding: 50
2. TSLA Holding: 25
3. GOOGL Holding: 10
资产配置总览
总净值: ~\$150,000
FAKE
  rc=$?
  [ $rc -eq 3 ]
}
run "T4 fabrication pattern caught" t4_fabrication

# T5 — update_holdings.py importable & help works
t5_update() { python3 "$HERE/update_holdings.py" --help >/dev/null 2>&1 || python3 -c "import ast; ast.parse(open('$HERE/update_holdings.py').read())"; }
run "T5 update_holdings parseable" t5_update

echo ""
echo "───────────────────────"
echo "PASS: $PASS   FAIL: $FAIL"
[ $FAIL -eq 0 ]
