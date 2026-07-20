# AIsa MarketPulse — API Response Formats

Verified against live API calls (2026-05-29). The shared `aisa_client.py` and all
skill scripts should reference these shapes, NOT assumed nested structures.

---

## `prices` — Historical OHLCV

**Endpoint**: `GET /apis/v1/financial/prices`
**Params**: `ticker`, `interval`, `interval_multiplier`, `start_date`, `end_date`

**Response shape** (HTTP 200):
```json
{
  "prices": [
    {
      "close":  270.17,
      "high":   271.04,
      "low":    267.04,
      "open":   267.55,
      "ticker": "AAPL",
      "time":   "2026-04-29",
      "volume": 30047869
    }
  ],
  "ticker": "AAPL"
}
```

**Key facts**:
- Top-level key is `"prices"` — **NOT** `data.results`, **NOT** `data.prices`
- Field names are **lowercase**: `close`, `open`, `high`, `low`, `time`, `volume`, `ticker`
- `time` is an ISO date string (YYYY-MM-DD) for daily bars
- For robust parsing, match both lowercase and PascalCase (`close` or `Close`, `time` or `timestamp` or `date`)
- Response is flat — no pagination wrapper

**Minimal Python parser** (urllib, no external deps):
```python
import json, urllib.request
url = f"https://api.aisa.one/apis/v1/financial/prices?ticker={ticker}&interval=day&interval_multiplier=1&start_date={start}&end_date={end}"
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
with urllib.request.urlopen(req, timeout=20) as resp:
    data = json.loads(resp.read())
results = data.get("prices", [])   # ← correct key
last = results[-1]
close_val = last.get("close") or last.get("Close") or last.get("c")
```

> **Common pitfall**: Writing `data.get("data", {}).get("results", [])` — this returns
> empty and causes silent fallback to Yahoo. The API has no `data` wrapper.

---

## `insider` — Insider Transactions

(TODO: verify and document after live API call)

## `institutional` — Institutional Holdings

(TODO: verify and document after live API call)

## `financials` — Financial Statements

(TODO: verify and document after live API call)
