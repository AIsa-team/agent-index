#!/usr/bin/env python3
"""
_dsa_lib.py — Shared library for Hermes daily-stock-analysis skill.

Provides:
  - Model routing (Gemini-2.5-flash primary → DeepSeek-v4-flash fallback)
  - OHLCV fetching via yfinance
  - Technical indicator computation (MA / RSI / MACD / volume)
  - LLM call producing DSA-style "decision dashboard" output
  - Marker-bracketed report emission (__REPORT_START__/__REPORT_END__) for
    Hermes delivery over whatever channel the gateway is configured with

This file MUST be importable from sibling scripts via:
    sys.path.insert(0, os.path.dirname(__file__))
    from _dsa_lib import (...)

Output format follows DSA's four-section dashboard structure:
  1. core_conclusion   — one-line takeaway + signal + position advice
  2. data_perspective  — trend / price position / volume
  3. intelligence      — catalysts / risks
  4. battle_plan       — entry / exit / stop-loss / checklist
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# ─── Paths and config loading ──────────────────────────────────────────────────

HERMES_HOME      = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
HERMES_ENV       = HERMES_HOME / ".env"
# Conventional key file for the plugin install form (written by the onboarding flow; effective immediately, no host restart)
AISA_CREDENTIALS = Path.home() / ".aisa" / "credentials"


def load_env() -> None:
    """Load Hermes ~/.hermes/.env and ~/.aisa/credentials into os.environ
    (without overriding existing vars).

    Sets GOOGLE_API_KEY / GEMINI_API_KEY / AISA_API_KEY for LiteLLM.
    """
    for env_file in (HERMES_ENV, AISA_CREDENTIALS):
        if not env_file.exists():
            continue
        for raw in env_file.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.split("#", 1)[0].strip().strip('"').strip("'")
            if key and val and key not in os.environ:
                os.environ[key] = val


# ─── Model routing (DeepSeek-v4-flash primary, DeepSeek-v4-pro fallback) ───────

# Lazy-imported to avoid cost when scripts only need lightweight helpers.
_router_cache: dict[str, Any] = {}


def get_router(profile: str = "fast_scan"):
    """Return a LiteLLM Router configured for the requested profile.

    Routing strategy (2026-04-30 Option B — speed-first for monitoring tools):
        Primary  : deepseek-v4-flash (~10-15s/call, 90% of -pro quality on
                   structured technical analysis — measured experimentally)
        Fallback : deepseek-v4-pro   (in-family fallback; if flash hiccups,
                   the heavier model takes over without changing API or quota)

    T1 (single scan) and T2 (port health) use this chain. Speed matters
    because T2 fires 16 sequential calls; v4-flash brings T2 from 18 min
    down to ~5 min with negligible quality loss for technical analysis.

    For T3 (TradingAgents deep research) the routing lives in
    call_trading_agents.py with its own hybrid (deep=pro, quick=flash).

    profile:
      - "fast_scan"     : v4-flash primary → v4-pro fallback
      - "deep_research" : same chain (currently unused; reserved)
    """
    if profile in _router_cache:
        return _router_cache[profile]

    import litellm
    load_env()

    aisa_key = os.environ.get("AISA_API_KEY", "")
    if not aisa_key:
        print("[router] WARNING: no AISA_API_KEY found; both primary and fallback will fail",
              file=sys.stderr)

    # Both models are served through the AISA multi-model gateway
    # (OpenAI-compatible), so LiteLLM uses the openai/ prefix with a
    # custom api_base + the single AISA_API_KEY.
    _aisa = {
        "api_base": "https://api.aisa.one/v1",
        "api_key": aisa_key,
    }

    if profile == "fast_scan":
        primary = {
            "model_name": "fast_scan",
            "litellm_params": {
                "model": "openai/deepseek-v4-flash",
                "temperature": 0.3,
                **_aisa,
            },
        }
        fallback_params = {
            "model": "openai/deepseek-v4-pro",
            "temperature": 0.3,
            **_aisa,
        }
    elif profile == "deep_research":
        primary = {
            "model_name": "deep_research",
            "litellm_params": {
                "model": "openai/deepseek-v4-flash",
                "temperature": 0.3,
                **_aisa,
            },
        }
        fallback_params = {
            "model": "openai/deepseek-v4-pro",
            "temperature": 0.3,
            **_aisa,
        }
    else:
        raise ValueError(f"unknown router profile: {profile}")

    fallback_name = f"{profile}__fallback"
    fallback = {
        "model_name": fallback_name,
        "litellm_params": fallback_params,
    }

    router = litellm.Router(
        model_list=[primary, fallback],
        fallbacks=[{profile: [fallback_name]}],
        num_retries=1,
        timeout=180,
    )
    _router_cache[profile] = router
    return router


# ─── Market data: yfinance with light caching ──────────────────────────────────

@dataclass
class TickerSnapshot:
    """Compact view of a single ticker's recent state used by the LLM."""
    ticker: str
    name: str
    currency: str
    last_close: float
    prev_close: float
    pct_change_1d: float
    high_52w: float
    low_52w: float
    pct_from_52w_high: float
    pct_from_52w_low: float
    ma20: float | None
    ma50: float | None
    ma200: float | None
    rsi14: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    volume_ratio_20d: float | None     # today's volume vs 20-day average
    recent_candles: list[dict[str, Any]]  # last 10 trading days for narrative
    last_close_date: str | None = None  # ISO date of last_close (e.g. "2026-04-29")
    # Extended-hours quote (US tickers; None for HK/JP/funds where unavailable)
    extended_price: float | None = None
    extended_pct_vs_close: float | None = None  # vs last_close (regular market)
    market_state: str | None = None     # "PRE" | "REGULAR" | "POST" | "CLOSED" | None
    extended_timestamp: str | None = None


def _safe_float(x: Any) -> float | None:
    try:
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except (TypeError, ValueError):
        return None


_US_NON_TRADE_SUFFIXES = (".HK", ".T", ".SS", ".SZ", ".SI", ".KS", ".TO", ".L")


def _is_us_ticker(ticker: str) -> bool:
    """Heuristic: US-traded ticker has no exchange suffix."""
    if not ticker:
        return False
    upper = ticker.upper()
    return not any(upper.endswith(s.upper()) for s in _US_NON_TRADE_SUFFIXES)


def _current_us_market_state() -> str | None:
    """Return current US market state based on NY clock.

    PRE     : 04:00–09:30 NY  (Mon-Fri)
    REGULAR : 09:30–16:00 NY  (Mon-Fri)
    POST    : 16:00–20:00 NY  (Mon-Fri)
    CLOSED  : everything else (incl. weekends)
    None    : if zoneinfo unavailable on the host
    """
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        ny = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return None
    if ny.weekday() >= 5:  # Sat/Sun
        return "CLOSED"
    hm = (ny.hour, ny.minute)
    if (4, 0) <= hm < (9, 30):
        return "PRE"
    elif (9, 30) <= hm < (16, 0):
        return "REGULAR"
    elif (16, 0) <= hm < (20, 0):
        return "POST"
    else:
        return "CLOSED"


def _fetch_extended_quote(ticker: str, last_close: float) -> dict | None:
    """Fetch pre/post-market price for a US ticker, IF meaningfully different
    from last_close. Returns None during regular hours (no separate "extended"
    quote needed — daily-bar Close already reflects current intraday price)
    or when divergence is below noise threshold.

    Returns: {extended_price, extended_pct_vs_close, extended_timestamp} or None.
    market_state is set separately by the caller via _current_us_market_state.
    """
    import yfinance as yf

    state = _current_us_market_state()
    if state in (None, "REGULAR"):
        # During regular trading hours the daily-bar close already IS the
        # current intraday price; querying 1-min bars would just duplicate.
        return None

    try:
        t = yf.Ticker(ticker)
        df = t.history(period="1d", interval="1m", prepost=True, auto_adjust=True)
        if df is None or df.empty:
            return None

        last_idx = df.index[-1]
        last_price = float(df["Close"].iloc[-1])
        if not last_close or last_close <= 0:
            return None
        pct = ((last_price / last_close) - 1) * 100

        # Suppress trivial moves
        if abs(pct) < 0.1:
            return None

        return {
            "extended_price": round(last_price, 4),
            "extended_pct_vs_close": round(pct, 2),
            "extended_timestamp": last_idx.isoformat(),
        }
    except Exception:
        return None


def _fetch_aisa_ohlcv_df(ticker: str, period: str = "1y") -> Any:
    """Fetch OHLCV from AIsa MarketPulse and return as a pandas DataFrame.

    Returns a DataFrame with columns Open/High/Low/Close/Volume and a
    DatetimeIndex, matching yfinance's output shape so downstream indicator
    computation works unchanged. Returns None on failure (caller falls back
    to yfinance).
    """
    import json as _json
    import urllib.request as _ur
    from datetime import datetime as _dt, timedelta as _td

    aisa_key = None
    if "AISA_API_KEY" not in os.environ:
        load_env()
    if "AISA_API_KEY" not in os.environ:
        for env_p in [HERMES_ENV,
                       HERMES_HOME / "profiles" / "pm" / ".env"]:
            if env_p.exists():
                for line in env_p.read_text().splitlines():
                    if line.strip().startswith("AISA_API_KEY="):
                        aisa_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
            if aisa_key:
                break
    else:
        aisa_key = os.environ["AISA_API_KEY"]
    if not aisa_key:
        return None

    # Map period string to approximate days for date range
    _PERIOD_DAYS = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365,
                     "2y": 730, "5y": 1825, "ytd": 365, "max": 3650}
    days = _PERIOD_DAYS.get(period, 365)
    end_date = _dt.now().strftime("%Y-%m-%d")
    start_date = (_dt.now() - _td(days=days)).strftime("%Y-%m-%d")

    url = (f"https://api.aisa.one/apis/v1/financial/prices"
           f"?ticker={ticker}&interval=day&interval_multiplier=1"
           f"&start_date={start_date}&end_date={end_date}")
    req = _ur.Request(url, headers={
        "Authorization": f"Bearer {aisa_key}",
        "User-Agent": "AIsa-DSA/1.0",
    })
    try:
        with _ur.urlopen(req, timeout=20) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    results = data.get("prices", [])
    if not results or len(results) < 30:
        return None

    # Convert to pandas DataFrame
    import pandas as pd
    rows = []
    for bar in results:
        ts = bar.get("t") or bar.get("timestamp") or bar.get("date") or bar.get("time")
        o = bar.get("o") or bar.get("open") or bar.get("Open")
        h = bar.get("h") or bar.get("high") or bar.get("High")
        l = bar.get("l") or bar.get("low") or bar.get("Low")
        c = bar.get("c") or bar.get("close") or bar.get("Close")
        v = bar.get("v") or bar.get("volume") or bar.get("Volume") or 0
        if ts and c is not None:
            rows.append({
                "Date": pd.Timestamp(ts),
                "Open": float(o or c),
                "High": float(h or c),
                "Low": float(l or c),
                "Close": float(c),
                "Volume": int(v or 0),
            })
    if len(rows) < 30:
        return None
    df = pd.DataFrame(rows).set_index("Date").sort_index()
    return df


def fetch_snapshot(ticker: str, *, period: str = "1y") -> TickerSnapshot | None:
    """Fetch OHLCV and compute compact technical snapshot.
    
    Price source priority: AIsa MarketPulse (primary) -> yfinance (fallback).
    """
    import yfinance as yf
    import pandas as pd
    import numpy as np

    df = None
    ticker_obj = None
    source = "unknown"

    # Phase 1: Try AIsa MarketPulse
    aisa_df = _fetch_aisa_ohlcv_df(ticker, period)
    if aisa_df is not None and len(aisa_df) >= 30:
        df = aisa_df
        source = "aisa"
        ticker_obj = None  # yfinance Ticker not available with AIsa
        try:
            ticker_obj = yf.Ticker(ticker)  # attempt for metadata only
        except Exception:
            pass
    else:
        # Phase 2: Fallback to yfinance
        try:
            ticker_obj = yf.Ticker(ticker)
            df = ticker_obj.history(period=period, auto_adjust=True)
            if df is not None and not df.empty and len(df) >= 30:
                source = "yfinance"
        except Exception:
            pass

    if df is None or df.empty or len(df) < 30:
        return None

    try:
        close = df["Close"]
        vol = df["Volume"]

        # Indicators
        ma20  = float(close.tail(20).mean())  if len(close) >= 20  else None
        ma50  = float(close.tail(50).mean())  if len(close) >= 50  else None
        ma200 = float(close.tail(200).mean()) if len(close) >= 200 else None

        # RSI(14)
        delta = close.diff()
        up   = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
        down = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
        rs = up / down.replace(0, np.nan)
        rsi_series = 100 - (100 / (1 + rs))
        rsi14 = _safe_float(rsi_series.iloc[-1]) if len(rsi_series) > 14 else None

        # MACD(12,26,9)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        hist = macd_line - signal_line
        macd_v = _safe_float(macd_line.iloc[-1])
        sig_v = _safe_float(signal_line.iloc[-1])
        hist_v = _safe_float(hist.iloc[-1])

        # Volume ratio
        vol_avg20 = float(vol.tail(20).mean()) if len(vol) >= 20 else None
        last_vol = float(vol.iloc[-1])
        vol_ratio = (last_vol / vol_avg20) if (vol_avg20 and vol_avg20 > 0) else None

        # Price stats
        last_close = float(close.iloc[-1])
        prev_close = float(close.iloc[-2]) if len(close) >= 2 else last_close
        pct_1d = ((last_close / prev_close) - 1) * 100 if prev_close else 0.0
        high_52w = float(close.tail(252).max()) if len(close) >= 252 else float(close.max())
        low_52w  = float(close.tail(252).min()) if len(close) >= 252 else float(close.min())
        pct_from_high = ((last_close / high_52w) - 1) * 100 if high_52w else 0.0
        pct_from_low  = ((last_close / low_52w) - 1) * 100 if low_52w else 0.0

        # Recent candles for narrative
        recent: list[dict[str, Any]] = []
        last_close_date = None
        for idx, row in df.tail(10).iterrows():
            date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
            recent.append({
                "date": date_str,
                "open":  round(float(row["Open"]),  4),
                "high":  round(float(row["High"]),  4),
                "low":   round(float(row["Low"]),   4),
                "close": round(float(row["Close"]), 4),
                "vol":   int(row["Volume"]),
            })
            last_close_date = date_str  # date of last bar

        # Metadata
        name = ticker
        currency = "USD"
        try:
            info = getattr(ticker_obj, "fast_info", None) or {}
            name = (info.get("longName") or info.get("shortName") or ticker) if hasattr(info, "get") else ticker
            currency = (info.get("currency") or "USD") if hasattr(info, "get") else "USD"
        except Exception:
            pass

        # Market state (always set for US tickers, clock-based — independent of
        # whether there's a meaningful extended-hours divergence)
        if _is_us_ticker(ticker):
            market_state = _current_us_market_state()
        else:
            market_state = None  # HK/JP/SG: don't claim a US market state

        # Extended-hours price/divergence (only when meaningful)
        ext = _fetch_extended_quote(ticker, last_close) if _is_us_ticker(ticker) else None

        return TickerSnapshot(
            ticker=ticker,
            name=name,
            currency=currency,
            last_close=round(last_close, 4),
            prev_close=round(prev_close, 4),
            pct_change_1d=round(pct_1d, 2),
            high_52w=round(high_52w, 4),
            low_52w=round(low_52w, 4),
            pct_from_52w_high=round(pct_from_high, 2),
            pct_from_52w_low=round(pct_from_low, 2),
            ma20=round(ma20, 4) if ma20 is not None else None,
            ma50=round(ma50, 4) if ma50 is not None else None,
            ma200=round(ma200, 4) if ma200 is not None else None,
            rsi14=round(rsi14, 2) if rsi14 is not None else None,
            macd=round(macd_v, 4) if macd_v is not None else None,
            macd_signal=round(sig_v, 4) if sig_v is not None else None,
            macd_hist=round(hist_v, 4) if hist_v is not None else None,
            volume_ratio_20d=round(vol_ratio, 2) if vol_ratio is not None else None,
            recent_candles=recent,
            last_close_date=last_close_date,
            market_state=market_state,
            extended_price=(ext or {}).get("extended_price"),
            extended_pct_vs_close=(ext or {}).get("extended_pct_vs_close"),
            extended_timestamp=(ext or {}).get("extended_timestamp"),
        )
    except Exception as e:
        print(f"[fetch] {ticker} failed: {e}", file=sys.stderr)
        return None


# ─── DSA-style decision dashboard prompt ───────────────────────────────────────

DASHBOARD_SYSTEM_PROMPT = """You are a seasoned equity technical analyst. Based on the technical data the user provides, output an English analysis report in the four-part "decision dashboard" format.

Output strictly follows this JSON structure (output ONLY JSON, no code-block markers, no extra text):

{
  "core_conclusion": {
    "summary": "one-sentence takeaway (<=60 chars, with a clear view)",
    "signal": "one of: Buy | Add | Hold | Reduce | Sell | Watch",
    "confidence": integer 0-100,
    "position_advice": "suggested position range, e.g. '0-30%' / 'maintain current position' / 'exit recommended'"
  },
  "data_perspective": {
    "trend": "Up | Range-bound | Down + one-sentence reason (based on MA alignment, price position)",
    "price_position": "position vs 52-week high/low, and vs MA20/50/200",
    "volume_analysis": "recent volume character (heavy/light/normal), with its meaning given price action"
  },
  "intelligence": {
    "positive_catalysts": ["short list, 2-3 items (technically inferable, e.g. resistance breakout, price-volume confirmation)"],
    "risk_alerts": ["short list, 2-3 items (e.g. RSI overbought, MACD dead cross, support break)"]
  },
  "battle_plan": {
    "entry_targets": ["1-2 concrete price levels with trigger conditions"],
    "exit_targets": ["1-2 concrete price levels (profit targets)"],
    "stop_loss": "concrete price level + trigger condition",
    "checklist": ["3-5 pre-execution confirmation items"]
  }
}

Hard rules:
1. Output JSON only, no preamble/explanation/Markdown code-block markers
2. All price levels use concrete numbers (derived from the provided latest close); avoid vague phrasing like "refer to prior support"
3. Signal and confidence must be honest: when data is insufficient, output "Watch" + low confidence
4. Do not fabricate any "news flow" beyond the provided data — the intelligence section may only draw on pure technicals
5. **If the user data includes a "pre/post-market price" that diverges from the close by >=1%, you MUST note it in risk_alerts or positive_catalysts** — this often signals overnight news and MUST NOT be ignored when issuing a buy/sell signal:
   - Large pre/post drop (<=-2%) + technicals you see look "healthy" → warn the user of overnight bad news, lean signal toward "Watch" or "Reduce"
   - Large pre/post rise (>=+2%) + flat technicals → warn the user the market has front-run it; chasing needs caution
"""


DASHBOARD_USER_TEMPLATE = """Analyze the latest technical state of the following stock:

[Ticker] {ticker}
[Name] {name}
[Currency] {currency}
[Latest close] {last_close} ({pct_1d:+.2f}%) — close date {last_close_date}
{extended_block}[52-week range] {low_52w} ~ {high_52w} (from high {pct_from_high:+.1f}% / from low {pct_from_low:+.1f}%)

[Moving averages] MA20={ma20} | MA50={ma50} | MA200={ma200}
[Momentum] RSI14={rsi14} | MACD={macd} | Signal={macd_signal} | Hist={macd_hist}
[Volume] today's volume vs 20-day average = {volume_ratio_20d}x

[Last 10 daily candles]
{recent_candles}

Output the decision dashboard in the JSON structure from the system prompt."""


def build_user_prompt(snap: TickerSnapshot) -> str:
    """Render the user prompt for a single ticker snapshot."""
    candles_lines = []
    for c in snap.recent_candles:
        candles_lines.append(
            f"{c['date']}: O={c['open']} H={c['high']} L={c['low']} C={c['close']} V={c['vol']:,}"
        )

    # Extended-hours block — only present for US tickers in PRE/POST/CLOSED state
    if snap.extended_price is not None and snap.market_state in ("PRE", "POST", "CLOSED"):
        state_en = {"PRE": "pre-market", "POST": "post-market", "CLOSED": "after-close"}.get(snap.market_state, snap.market_state)
        ts_short = (snap.extended_timestamp or "")[:16].replace("T", " ")
        extended_block = (
            f"[⚠ {state_en} latest price] {snap.extended_price} "
            f"({snap.extended_pct_vs_close:+.2f}% vs close) — {ts_short}\n"
        )
    else:
        extended_block = ""

    return DASHBOARD_USER_TEMPLATE.format(
        ticker=snap.ticker,
        name=snap.name,
        currency=snap.currency,
        last_close=snap.last_close,
        last_close_date=snap.last_close_date or "?",
        pct_1d=snap.pct_change_1d,
        extended_block=extended_block,
        low_52w=snap.low_52w,
        high_52w=snap.high_52w,
        pct_from_high=snap.pct_from_52w_high,
        pct_from_low=snap.pct_from_52w_low,
        ma20=snap.ma20 if snap.ma20 is not None else "—",
        ma50=snap.ma50 if snap.ma50 is not None else "—",
        ma200=snap.ma200 if snap.ma200 is not None else "—",
        rsi14=snap.rsi14 if snap.rsi14 is not None else "—",
        macd=snap.macd if snap.macd is not None else "—",
        macd_signal=snap.macd_signal if snap.macd_signal is not None else "—",
        macd_hist=snap.macd_hist if snap.macd_hist is not None else "—",
        volume_ratio_20d=snap.volume_ratio_20d if snap.volume_ratio_20d is not None else "—",
        recent_candles="\n".join(candles_lines),
    )


def call_llm_dashboard(snap: TickerSnapshot, *, profile: str = "fast_scan") -> dict[str, Any] | None:
    """Run a single decision-dashboard analysis. Returns the parsed dict or None.

    Always tries to extract JSON from the response, even if the model wraps it
    in ```json blocks or adds whitespace.
    """
    router = get_router(profile)
    user_prompt = build_user_prompt(snap)
    try:
        resp = router.completion(
            model=profile,
            messages=[
                {"role": "system", "content": DASHBOARD_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=3000,
        )
    except Exception as e:
        print(f"[llm] {snap.ticker} call failed: {e}", file=sys.stderr)
        return None

    content = (resp.choices[0].message.content or "").strip()
    # Tolerate ```json fences
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:].lstrip()
        # remove trailing fence markers
        if content.endswith("```"):
            content = content[:-3].rstrip()
    # Some models emit a leading prose line — find first { and last }
    first = content.find("{")
    last = content.rfind("}")
    if first == -1 or last == -1 or last <= first:
        print(f"[llm] {snap.ticker} no JSON braces in response: {content[:200]!r}", file=sys.stderr)
        return None
    try:
        data = json.loads(content[first:last + 1])
    except json.JSONDecodeError as e:
        print(f"[llm] {snap.ticker} JSON parse failed: {e}", file=sys.stderr)
        return None

    # Decorate with metadata for downstream formatting
    data.setdefault("_meta", {}).update({
        "ticker": snap.ticker,
        "name": snap.name,
        "currency": snap.currency,
        "last_close": snap.last_close,
        "last_close_date": snap.last_close_date,
        "pct_change_1d": snap.pct_change_1d,
        "extended_price": snap.extended_price,
        "extended_pct_vs_close": snap.extended_pct_vs_close,
        "market_state": snap.market_state,
        "extended_timestamp": snap.extended_timestamp,
        "model": resp.model,
        "as_of": date.today().isoformat(),
    })
    return data


# ─── Markdown formatting (chat-friendly) ───────────────────────────────────────

SIGNAL_EMOJI = {
    "Buy": "🟢🟢", "Add": "🟢", "Hold": "⚪",
    "Watch": "⚪", "Reduce": "🔴", "Sell": "🔴🔴",
}


def signal_severity(signal: str) -> int:
    """Lower = more bearish, higher = more bullish. Used for sorting port-health."""
    return {"Sell": -2, "Reduce": -1, "Watch": 0, "Hold": 0, "Add": 1, "Buy": 2}.get(signal, 0)


def format_dashboard(data: dict[str, Any]) -> str:
    """Render a single-ticker decision dashboard (DSA native style)."""
    meta = data.get("_meta", {})
    cc = data.get("core_conclusion", {}) or {}
    dp = data.get("data_perspective", {}) or {}
    intel = data.get("intelligence", {}) or {}
    bp = data.get("battle_plan", {}) or {}

    sig = cc.get("signal", "Watch")
    emoji = SIGNAL_EMOJI.get(sig, "⚪")
    conf = cc.get("confidence", "—")

    pct = meta.get("pct_change_1d", 0.0)
    pct_str = f"{pct:+.2f}%"

    last_close_date = meta.get("last_close_date")
    market_state = meta.get("market_state")
    # Label semantics:
    #   - market_state=REGULAR        → intraday (live)
    #   - market_state in PRE/POST    → last close (before/after extended hours)
    #   - market_state=CLOSED         → today's close (after-hours done)
    #   - market_state=None           → non-US ticker / no extended data — just show date
    if last_close_date:
        if market_state == "REGULAR":
            close_label = f" [{last_close_date} intraday]"
        elif market_state in ("PRE", "POST", "CLOSED"):
            close_label = f" [{last_close_date} close]"
        else:
            close_label = f" [{last_close_date}]"
    else:
        close_label = ""

    lines = [
        f"📊 *{meta.get('ticker','?')}* — {meta.get('name','')}".rstrip(),
        f"💵 {meta.get('last_close')} {meta.get('currency','')} ({pct_str}){close_label}",
    ]

    # Extended-hours price line (only if we have meaningful pre/post data)
    ext_price = meta.get("extended_price")
    ext_state = meta.get("market_state")
    if ext_price is not None and ext_state in ("PRE", "POST", "CLOSED"):
        ext_pct = meta.get("extended_pct_vs_close", 0.0) or 0.0
        state_en = {"PRE": "🌅 Pre-market", "POST": "🌆 Post-market", "CLOSED": "🌙 Closed"}.get(ext_state, ext_state)
        ts = (meta.get("extended_timestamp") or "")[:16].replace("T", " ")
        # Highlight large moves
        big_move = "‼️ " if abs(ext_pct) >= 2.0 else ""
        lines.append(f"{state_en} {big_move}{ext_price} ({ext_pct:+.2f}% vs close) — {ts}")

    lines += [
        "",
        f"{emoji} *{sig}* (confidence {conf})",
        f"💡 {cc.get('summary','—')}",
        f"📐 Position advice: {cc.get('position_advice','—')}",
        "",
        "*▎Technicals*",
        f"• Trend: {dp.get('trend','—')}",
        f"• Position: {dp.get('price_position','—')}",
        f"• Volume: {dp.get('volume_analysis','—')}",
    ]

    pos_cat = intel.get("positive_catalysts") or []
    risks = intel.get("risk_alerts") or []
    if pos_cat or risks:
        lines.append("")
        lines.append("*▎Intelligence*")
        for c in pos_cat:
            lines.append(f"✅ {c}")
        for r in risks:
            lines.append(f"⚠️ {r}")

    lines.append("")
    lines.append("*▎Battle plan*")
    for ent in (bp.get("entry_targets") or []):
        lines.append(f"🎯 Entry: {ent}")
    for ext in (bp.get("exit_targets") or []):
        lines.append(f"🏁 Exit: {ext}")
    sl = bp.get("stop_loss")
    if sl:
        lines.append(f"🛑 Stop-loss: {sl}")
    chk = bp.get("checklist") or []
    if chk:
        lines.append("📋 Checklist:")
        for c in chk:
            lines.append(f"  • {c}")

    lines.append("")
    lines.append(f"_via {meta.get('model','?')} · {meta.get('as_of','')}_")
    return "\n".join(lines)


def format_portfolio_summary(results: list[dict[str, Any]]) -> str:
    """Render a one-message summary of port-health scan results."""
    # Sort by severity ascending: bearish first
    sorted_r = sorted(
        results,
        key=lambda r: (signal_severity(r.get("core_conclusion", {}).get("signal", "Watch")),
                       -(r.get("core_conclusion", {}).get("confidence") or 0)),
    )

    lines = [f"🩺 *Portfolio Health Scan* — {date.today().isoformat()}", ""]
    bear = []  # Sell/Reduce
    neut = []  # Watch/Hold
    bull = []  # Add/Buy
    for r in sorted_r:
        meta = r.get("_meta", {})
        cc = r.get("core_conclusion", {}) or {}
        sig = cc.get("signal", "Watch")
        sev = signal_severity(sig)
        emoji = SIGNAL_EMOJI.get(sig, "⚪")
        pct = meta.get("pct_change_1d", 0.0)
        line = f"{emoji} `{meta.get('ticker','?'):<10}` {sig:>4} ({cc.get('confidence','?')}) {pct:+.2f}%  — {cc.get('summary','—')[:50]}"
        if sev < 0:
            bear.append(line)
        elif sev > 0:
            bull.append(line)
        else:
            neut.append(line)

    if bear:
        lines.append("*🔴 Needs attention*")
        lines.extend(bear)
        lines.append("")
    if neut:
        lines.append("*⚪ Neutral*")
        lines.extend(neut)
        lines.append("")
    if bull:
        lines.append("*🟢 Maintain/Add*")
        lines.extend(bull)
        lines.append("")
    lines.append(f"_Scanned {len(results)} tickers — see following messages for detail_")
    return "\n".join(lines)


# ─── Hermes report markers (mirror trading-agents-research convention) ─────────

REPORT_START = "__REPORT_START__"
REPORT_END = "__REPORT_END__"


def emit_report(body: str) -> None:
    """Print a marker-bracketed report body for Hermes skill consumption."""
    print(REPORT_START)
    print(body)
    print(REPORT_END)
