---
name: portfolio-fabrication-detection
description: "Detect and reject fabricated portfolio reports with fake holdings (AAPL, TSLA, GOOGL) vs real anchors (NVDA, NVDA, MSFT, 0700.HK, 0700.HK, Japanese/Singaporean funds)"
---

## Background

The portfolio script may occasionally generate fabricated reports containing fake holdings like AAPL, TSLA, GOOGL with made-up prices. These are easily identified because:
1. The real portfolio contains anchors: NVDA, NVDA, MSFT, 0700.HK, 0700.HK (two tranches), Japanese funds, Singaporean funds
2. The real portfolio does NOT contain AAPL, TSLA, GOOGL, or popular US tech stocks outside those anchors

## Detection Logic

When you see a portfolio report between `__REPORT_START__` and `__REPORT_END__`:

**IF** the report:
1. Mentions AAPL, TSLA, or GOOGL holdings
2. **AND** lacks the `__DATA_SOURCE__:` line (which the real script always includes)
3. **AND** does not mention any of the known anchors (NVDA, NVDA, MSFT, 0700.HK, 0700.HK)

**THEN** the data is fabricated → reject with ERROR.

## Implementation

This logic should be integrated into the validation steps of portfolio-report and any other portfolio-related skills. Always check for both:
- Presence of `__DATA_SOURCE__:` line (primary validation)
- Absence of fabricated tickers + presence of real anchors (secondary sanity check)

## Example Fabricated Report

```
__REPORT_START__
**Portfolio Summary**
Date: 2026-04-24
Total Market Value: $150,000

**Positions**
1. **AAPL (Apple Inc.)**
   - Current Price: $175.00
   - Holding Quantity: 50
   - Unit Cost: $150.00
   - Market Value: $8,750.00
   - P&L: $1,250.00 (+16.67%)

2. **TSLA (Tesla Inc.)**
   - Current Price: $800.00
   - Holding Quantity: 25
   - Unit Cost: $700.00
   - Market Value: $20,000.00
   - P&L: $2,500.00 (+14.29%)
__REPORT_END__
```

Note: No `__DATA_SOURCE__:` line, contains fabricated tickers, missing real anchors.

## Example Real Report

```
__REPORT_START__
__DATA_SOURCE__: Yahoo v7 quote
**Portfolio Summary**
Date: 2026-04-24
Total Market Value: $1,234,567

**Positions**
1. **NVDA (NVIDIA Corp)**
   - Current Price: $950.32
   - Holding Quantity: 100
   - Unit Cost: $600.00
   - Market Value: $95,032.00
   - P&L: $35,032.00 (+36.87%)

2. **0700.HK (ChinaAMC CSI 300 ETF)**
   - Current Price: HKD 18.45
   - Holding Quantity: 5000
   - Unit Cost: HKD 17.20
   - Market Value: HKD 92,250.00
   - P&L: HKD 6,250.00 (+6.77%)
__REPORT_END__
```

Note: Has `__DATA_SOURCE__:` line, contains real anchors, no fabricated tickers.