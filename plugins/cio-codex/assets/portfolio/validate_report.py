#!/usr/bin/env python3
"""
validate_report.py — Anti-fabrication sentinel.

Reads a portfolio-report text (via stdin or file arg) and checks that it is
genuine output from portfolio_report.py, NOT a hallucinated reply.

Exit codes:
  0 — report looks genuine (passes all checks)
  1 — report is empty
  2 — missing __DATA_SOURCE__ sentinel (script did not run, or output was
      assembled by the model from memory)
  3 — contains hallucination marker tickers NOT in known holdings
  4 — missing expected Chinese section headers

Can be used:
  - Offline: python3 validate_report.py report.txt
  - Piped:   portfolio_report.py | python3 validate_report.py -
  - As library: from validate_report import validate
"""

import sys, re, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRUTH_PATH = HERE / "portfolio_truth.json"

# Tickers that are known NOT to be in this portfolio. If a report lists these,
# it's fabricated — the gpt-4o failure mode produced exactly this set.
KNOWN_FABRICATION_TICKERS = {'AAPL', 'TSLA', 'GOOGL', 'AMZN', 'MSFT'}
# MSFT is included because it's a generic default hallucination target, even
# though the user could plausibly own it one day. If you ever do buy MSFT,
# remove it from this set.

# Section headers the real script always emits.
REQUIRED_SECTION_FRAGMENTS = ['资产配置总览', '总净值']


def _load_truth_tickers():
    try:
        data = json.loads(TRUTH_PATH.read_text())
        items = data if isinstance(data, list) else data.get('items', [])
        out = set()
        for it in items:
            t = (it.get('yahoo_ticker') or '').upper().strip()
            if t and not t.startswith('CODE:'):
                out.add(t)
                # also add the non-suffixed form (NVDA from NVDA, MSFT from MSFT)
                out.add(t.split('.')[0])
        return out
    except Exception:
        return set()


def validate(text: str):
    """Returns (exit_code, reason). 0 = genuine."""
    text = text.strip()
    if not text:
        return 1, 'empty report'

    if '__DATA_SOURCE__' not in text:
        return 2, 'missing __DATA_SOURCE__ sentinel (did the script actually run?)'

    real_tickers = _load_truth_tickers()
    fabrication_hits = []
    for t in KNOWN_FABRICATION_TICKERS:
        # Skip if user actually owns it
        if t in real_tickers:
            continue
        # Match as whole word (avoid false positives like "TSLA" in a URL)
        if re.search(rf'\b{re.escape(t)}\b', text):
            fabrication_hits.append(t)
    if fabrication_hits:
        return 3, f'fabrication-marker tickers present: {",".join(sorted(fabrication_hits))}'

    missing_sections = [s for s in REQUIRED_SECTION_FRAGMENTS if s not in text]
    if missing_sections:
        return 4, f'missing expected section(s): {missing_sections}'

    return 0, 'ok'


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else '-'
    if arg == '-':
        text = sys.stdin.read()
    else:
        text = Path(arg).read_text()
    code, reason = validate(text)
    print(f'validate_report: {reason} (exit {code})', file=sys.stderr)
    sys.exit(code)
