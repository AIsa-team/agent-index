"""
call_trading_agents.py
Three-tier stock research entry point.

  quick ("research TICKER")      : single-pass quick take — data pull + ONE
                                   flash LLM call, no TradingAgents. Runs
                                   synchronously, target < 1 min.
  deep  ("deep-research TICKER") : real TradingAgents framework, reduced
                                   pipeline (market+fundamentals analysts,
                                   all-flash models). Background, target ~3 min.
  full  ("full-report TICKER")   : real TradingAgents framework, complete
                                   pipeline (4 analysts, hybrid pro+flash).
                                   Background, ~9 min, no time constraint.

Legacy mode name "fast" is accepted as an alias for "deep" (old caches under
the `-fast` suffix are NOT migrated; they age out naturally — caches are
per-day files).

Delivery: results are cached to ~/.tradingagents/results/<TICKER>/ (raw JSON
+ formatted report.txt) and the report is printed to stdout on --resend;
the Hermes agent relays it over its own reply channel. No direct
chat-platform API calls.

Output contract:
  quick        → prints the quick report directly (synchronous)
  deep resend  → BRIEF report by default (decision + trading plan + tip);
                 pass full_text=True / --full-text for the whole deep output
  full resend  → complete report with readable debate/risk formatting

Optimisations (2026-04-26):
  #4  python3: background subprocess uses sys.executable (hermes venv python3)
  #7  Result cached to ~/.tradingagents/results/<TICKER>/<date>-result.json
      (+ <date>-report.txt); --resend re-prints without re-running TA
  #9  run_in_background() launches TA as a detached subprocess and returns
      immediately with STARTED: so the LLM conversation is never blocked

Three-tier redesign (2026-08-05, RY):
  - modes renamed full/fast -> full/deep, new synchronous "quick" tier
  - deep/quick resend prints a brief report; debate transcripts stay on disk
  - full report renders debate/risk state as readable sections instead of
    raw json.dumps
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, timedelta

AISA_API_KEY_ENV  = "AISA_API_KEY"
GEMINI_API_KEY_ENV   = "GEMINI_API_KEY"
GOOGLE_API_KEY_ENV   = "GOOGLE_API_KEY"
CACHE_DIR         = os.environ.get("TA_CACHE_DIR", os.path.expanduser("~/.tradingagents/results"))

AISA_CHAT_URL = "https://api.aisa.one/v1/chat/completions"
QUICK_MODEL   = "deepseek-v4-flash"

# Resolve this script's own path early (works both when imported via importlib
# and run directly); the profile dir is derived from it so config discovery
# works even when the gateway does not export the profile .env into os.environ.
try:
    SCRIPT_PATH = os.path.realpath(__file__)
except NameError:
    SCRIPT_PATH = os.path.realpath(os.path.join(os.path.dirname(__file__), "call_trading_agents.py"))

# <profile>/skills/trading-agents-research/scripts/call_trading_agents.py -> <profile>
_PROFILE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_PATH))))
# <profile>/skills — sibling skills (marketpulse) live here
_SKILLS_DIR  = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_PATH)))

# .env lookup order: profile .env (bootstrap.sh writes TA_DIR/TA_VENV_PYTHON
# there), then the global hermes .env.
_ENV_PATHS = [
    os.path.join(_PROFILE_DIR, ".env"),
    os.path.join(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")), ".env"),
    # plugin 安装形态的约定 key 文件(引导流程写入,写完即生效不用重启宿主)
    os.path.expanduser("~/.aisa/credentials"),
]

def _read_env_value(key: str) -> str:
    """Read a KEY=value line from the profile/global .env files, else os.environ.

    Canonical .env handling:
      - "FOO=bar"               -> "bar"
      - "FOO=bar  # note"       -> "bar"  (inline comment stripped)
      - 'FOO="bar # in-quote"'  -> "bar # in-quote"  (quoted: leave intact)
    """
    for env_path in _ENV_PATHS:
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{key}="):
                        val = line[len(key) + 1:].strip()
                        # Strip inline comment only if value is unquoted
                        if val and val[0] not in ("'", '"') and "#" in val:
                            val = val.split("#", 1)[0].strip()
                        val = val.strip("'").strip('"')
                        if val:
                            return val
        except Exception:
            continue
    return os.environ.get(key, "")

def _resolve_ta_paths() -> tuple:
    """Resolve (TA_DIR, TA_VENV_PYTHON): env var -> .env files -> the
    conventional bootstrap.sh install location (<profile>/TradingAgents)."""
    ta_dir = os.environ.get("TA_DIR") or _read_env_value("TA_DIR")
    ta_py = os.environ.get("TA_VENV_PYTHON") or _read_env_value("TA_VENV_PYTHON")
    if not ta_dir:
        candidate = os.path.join(_PROFILE_DIR, "TradingAgents")
        if os.path.isdir(os.path.join(candidate, "tradingagents")):
            ta_dir = candidate
    if not ta_py:
        # AgentSpec setup.python convention: <profile>/.venvs/ta
        candidate = os.path.join(_PROFILE_DIR, ".venvs", "ta", "bin", "python")
        if os.path.exists(candidate):
            ta_py = candidate
    if not ta_py and ta_dir:
        for name in ("python3", "python"):
            candidate = os.path.join(ta_dir, ".venv", "bin", name)
            if os.path.exists(candidate):
                ta_py = candidate
                break
    return ta_dir or "", ta_py or ""

TA_DIR, TA_VENV_PYTHON = _resolve_ta_paths()

def _ensure_ta_env() -> str:
    """Lazy self-provisioning: when TA_VENV_PYTHON is unresolved (e.g. the
    install skipped optional setup via AGENT_SKIP_OPTIONAL_SETUP=1), build the
    `ta` venv on first use with the same AgentSpec setup.python semantics —
    <profile>/.venvs/ta from <profile>/requirements/ta.txt — and persist
    TA_VENV_PYTHON into the profile .env. Returns the venv python, or ""."""
    req = os.path.join(_PROFILE_DIR, "requirements", "ta.txt")
    if not os.path.isfile(req):
        return ""
    venv_dir = os.path.join(_PROFILE_DIR, ".venvs", "ta")
    py = os.path.join(venv_dir, "bin", "python")
    if not os.path.exists(py):
        base = os.environ.get("AGENT_SETUP_PYTHON", "python3")
        print(f"[ta] first run: building TradingAgents venv from {req} "
              "(one-time, several minutes)…", file=sys.stderr, flush=True)
        try:
            subprocess.run([base, "-m", "venv", venv_dir],
                           check=True, capture_output=True, timeout=300)
            subprocess.run([py, "-m", "pip", "install", "-r", req],
                           check=True, capture_output=True, timeout=1800)
        except Exception as e:
            detail = ""
            if isinstance(e, subprocess.CalledProcessError) and e.stderr:
                detail = e.stderr.decode(errors="replace")[-300:]
            print(f"[ta] venv provisioning failed: {e}\n{detail}",
                  file=sys.stderr, flush=True)
            shutil.rmtree(venv_dir, ignore_errors=True)
            return ""
    # persist for future runs (idempotent upsert)
    try:
        env_path = os.path.join(_PROFILE_DIR, ".env")
        lines = []
        if os.path.exists(env_path):
            lines = [l for l in open(env_path).read().splitlines()
                     if not l.startswith("TA_VENV_PYTHON=")]
        lines.append(f"TA_VENV_PYTHON={py}")
        open(env_path, "w").write("\n".join(lines) + "\n")
    except Exception:
        pass  # venv still usable this run even if .env write fails
    return py

# Model routing (2026-04-30, revised — quality first, in-family fallback):
#   Primary  : DeepSeek-v4-pro (always reasons, native Chinese financial reasoning,
#              best-in-class for multi-agent debate role coherence within DeepSeek family)
#   Fallback : DeepSeek-v4-flash (same provider/endpoint, no separate quota, lighter
#              model. T3 fires 30+ LLM calls per ticker — Gemini free tier (20 RPD)
#              cannot serve as a real fallback for TA, so we stay in the DeepSeek
#              family for resilient process-level fallback.)
#   Both models are served through the AISA multi-model gateway (AISA_API_KEY).
#   Process-level fallback — if -pro config fails, retry entire ticker run with -flash.
#   The "gemini" provider config below is kept in code for future re-enabling
#   (e.g. when Gemini billing is upgraded) but is NOT in the active chain.
PROVIDER_CHAIN = ("deepseek", "deepseek_flash")

RUNNER_TEMPLATE = """\
import sys, os, json
# TA_DIR is legacy (source-checkout installs); with the AgentSpec `ta` venv the
# tradingagents package is pip-installed and importable without path insertion.
if {ta_dir!r}:
    sys.path.insert(0, {ta_dir!r})
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# Provider-specific API key env var (OPENAI_API_KEY for OpenAI-compatible
# providers like DeepSeek; GOOGLE_API_KEY for native Gemini).
os.environ[{api_key_env!r}] = {api_key!r}
{extra_env_lines}

config = DEFAULT_CONFIG.copy()
{backend_url_line}
config["llm_provider"]            = {llm_provider!r}
config["deep_think_llm"]          = {deep_think_llm!r}
config["quick_think_llm"]         = {quick_think_llm!r}
config["max_debate_rounds"]       = 1
config["max_risk_discuss_rounds"] = 1
{thinking_config_line}

ta = TradingAgentsGraph({selected_analysts_arg}debug=False, config=config)
final_state, decision = ta.propagate({ticker!r}, {trade_date!r})

def _str(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)

result = {{
    "success": True,
    "ticker": {ticker!r},
    "trade_date": {trade_date!r},
    "mode": {mode!r},
    "provider_used": {llm_provider!r},
    "model_used": {deep_think_llm!r},
    "decision": _str(decision),
    "ta_response": {{
        "final_trade_decision":    _str(final_state.get("final_trade_decision")),
        "trader_investment_plan":  _str(final_state.get("trader_investment_plan")),
        "investment_debate_state": _str(final_state.get("investment_debate_state")),
        "risk_debate_state":       _str(final_state.get("risk_debate_state")),
        "market_report":           _str(final_state.get("market_report")),
        "sentiment_report":        _str(final_state.get("sentiment_report")),
        "news_report":             _str(final_state.get("news_report")),
        "fundamentals_report":     _str(final_state.get("fundamentals_report")),
    }}
}}
# Print result as the last line so it can be parsed
print("__TA_RESULT__:" + json.dumps(result, ensure_ascii=False))
"""

VALID_MODES = ("quick", "deep", "full")

# Deep tier: official TradingAgentsGraph constructor arg — drop the News and
# Sentiment analyst branches (technicals + fundamentals form the decision
# skeleton; news/sentiment gaps are covered ad-hoc by `scan` / marketpulse).
DEEP_ANALYSTS = ("market", "fundamentals")

# Reminder appended to quick and deep outputs (user-facing, by product spec:
# both lighter tiers must point at the full report).
FULL_REPORT_TIP = (
    "Tip: for the complete multi-agent report (4 analysts + debate + risk, "
    "~9 min) run: full-report {ticker}"
)
QUICK_TIP = (
    "Tip: for multi-agent research run: deep-research {ticker} (~3 min, "
    "market+fundamentals) or full-report {ticker} (~9 min, complete report)."
)

def _normalize_mode(mode: str) -> str:
    """Map legacy names onto the three-tier scheme; raise on unknowns."""
    if mode == "fast":       # legacy alias, pre-2026-08 callers
        return "deep"
    if mode not in VALID_MODES:
        raise ValueError(f"unknown research mode {mode!r} (expected one of {VALID_MODES})")
    return mode

def _build_runner_args(provider: str, ticker: str, trade_date: str,
                       mode: str = "full") -> dict | None:
    """Resolve provider-specific args for RUNNER_TEMPLATE.

    Returns a dict suitable for ``RUNNER_TEMPLATE.format(**args)`` or None if
    the required API key is missing for this provider.

    ``mode="deep"`` reduces the pipeline: only market+fundamentals analysts
    and all-flash models (deep_think downgraded to the quick model).
    """
    reduced = mode == "deep"
    common = dict(
        ta_dir=TA_DIR,
        ticker=ticker.upper(),
        trade_date=trade_date,
        mode=mode,
        selected_analysts_arg=(
            f"selected_analysts={DEEP_ANALYSTS!r}, " if reduced else ""
        ),
    )

    if provider == "gemini":
        api_key = (_read_env_value(GEMINI_API_KEY_ENV)
                   or _read_env_value(GOOGLE_API_KEY_ENV))
        if not api_key:
            return None
        # IMPORTANT: route through Google's OpenAI-compatible endpoint, NOT
        # provider="google" (langchain_google_genai 4.2.2 has a 404 bug when
        # binding tools to gemini-2.5-flash via the native client).
        # OpenAI-compatible path uses ChatOpenAI which is battle-tested for
        # tool-calling and supports reasoning_effort directly.
        return {
            **common,
            "api_key_env":         "OPENAI_API_KEY",  # ChatOpenAI reads this
            "api_key":             api_key,
            "backend_url_line":    'config["backend_url"] = "https://generativelanguage.googleapis.com/v1beta/openai"',
            "llm_provider":        "openai",   # OpenAIClient w/ custom base_url -> Chat Completions path
            "deep_think_llm":      "gemini-2.5-flash",
            "quick_think_llm":     "gemini-2.5-flash",
            # Also expose GOOGLE_API_KEY/GEMINI_API_KEY in case any tool-side
            # code (e.g. embedding client, news fetcher) checks them.
            "extra_env_lines":     ('os.environ["GOOGLE_API_KEY"] = ' + repr(api_key) + '\n'
                                    'os.environ["GEMINI_API_KEY"] = ' + repr(api_key)),
            # openai_reasoning_effort=medium -> ChatOpenAI passes
            # reasoning_effort="medium" -> Google's endpoint enables thinking.
            "thinking_config_line": 'config["openai_reasoning_effort"] = "medium"',
        }

    if provider == "deepseek":
        api_key = _read_env_value(AISA_API_KEY_ENV)
        if not api_key:
            return None
        # DeepSeek models are served through the AISA gateway (OpenAI-
        # compatible); TradingAgents uses OpenAI client which picks up
        # OPENAI_API_KEY from env.
        # 2026-04-30 Option B (revised): hybrid model assignment.
        #   - deep_think_llm = v4-pro: ~5 calls per ticker (final IC memo,
        #     trader plan, judge synthesis). Quality matters here — this is
        #     where the user-facing decision quality is determined.
        #   - quick_think_llm = v4-flash: ~25 calls per ticker (analyst tool
        #     calls, debate turns, conditional logic). Short turns, no need
        #     for -pro depth. Cuts ~50% off total runtime (~14min -> ~8min).
        return {
            **common,
            "api_key_env":         "OPENAI_API_KEY",
            "api_key":             api_key,
            "backend_url_line":    'config["backend_url"] = "https://api.aisa.one/v1"',
            "llm_provider":        "deepseek",
            # deep tier: all-flash (deep_think downgraded); full keeps hybrid
            "deep_think_llm":      "deepseek-v4-flash" if reduced else "deepseek-v4-pro",
            "quick_think_llm":     "deepseek-v4-flash",
            # upstream openai_client requires DEEPSEEK_API_KEY for provider=deepseek
            "extra_env_lines":     'os.environ["DEEPSEEK_API_KEY"] = ' + repr(api_key),
            "thinking_config_line": "# DeepSeek V4 family always reasons; OpenAIClient disables in-history reasoning_content via extra_body",
        }

    if provider == "deepseek_flash":
        # In-family fallback: same provider, lighter model. Gemini free tier
        # can't sustain TA's 30+ call workload, so the safer fallback is the
        # lighter DeepSeek model (no separate quota).
        api_key = _read_env_value(AISA_API_KEY_ENV)
        if not api_key:
            return None
        return {
            **common,
            "api_key_env":         "OPENAI_API_KEY",
            "api_key":             api_key,
            "backend_url_line":    'config["backend_url"] = "https://api.aisa.one/v1"',
            "llm_provider":        "deepseek",
            "deep_think_llm":      "deepseek-v4-flash",
            "quick_think_llm":     "deepseek-v4-flash",
            "extra_env_lines":     'os.environ["DEEPSEEK_API_KEY"] = ' + repr(api_key),
            "thinking_config_line": "# deepseek-v4-flash always reasons; OpenAIClient disables in-history reasoning_content",
        }

    raise ValueError(f"unknown provider: {provider}")

# -- Cache helpers (#7) --------------------------------------------------------

def _mode_suffix(mode: str) -> str:
    """Filename infix for a mode: '' for full (legacy paths), '-deep'/'-quick'
    for the lighter tiers.

    Only known modes map to a suffix. An unknown mode raises instead of
    silently minting a `-<anything>` cache namespace — otherwise a future
    caller passing e.g. mode="speedy" would silently write into a separate
    cache that no resend path ever reads. (Legacy `-fast` caches are orphaned
    by the 2026-08 rename; caches are per-day files, they age out.)
    """
    mode = _normalize_mode(mode)
    return "" if mode == "full" else f"-{mode}"

def _cache_result(ticker: str, trade_date: str, result: dict,
                  mode: str = "full") -> str:
    """Persist result dict to ~/.tradingagents/results/<TICKER>/<date><suffix>-result.json.

    Full-mode paths are unchanged from the legacy layout; deep/quick get a
    suffix so the tiers never overwrite each other.
    Returns the cache file path.  Non-fatal: caller should catch exceptions.
    """
    cache_dir = os.path.join(CACHE_DIR, ticker)
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{trade_date}{_mode_suffix(mode)}-result.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path

def _load_cached_result(ticker: str, trade_date: str,
                        mode: str = "full") -> dict | None:
    """Load cached result for ticker/date/mode, or return None if not found."""
    path = os.path.join(CACHE_DIR, ticker,
                        f"{trade_date}{_mode_suffix(mode)}-result.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None

# -- Quick tier (single-pass, no TradingAgents) --------------------------------

def _run_json_cmd(argv: list, timeout: int = 25):
    """Run a subprocess expected to print JSON; return parsed JSON or None.

    The AIsa skill clients exit 0 even on API errors (the error only shows in
    the stdout JSON), so the payload is inspected for an "error" field."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict) and payload.get("error"):
        return None
    return payload

def _marketpulse(args: list):
    """Call the sibling marketpulse skill client (AIsa gateway, SOUL data-source
    priority #1). Returns parsed JSON or None when unavailable/failed."""
    client = os.path.join(_SKILLS_DIR, "marketpulse", "scripts", "market_client.py")
    if not os.path.isfile(client):
        return None
    return _run_json_cmd([sys.executable, client, "stock"] + args)

def _extract_closes(payload):
    """Best-effort extraction of (closes, volumes) oldest→newest from a
    marketpulse prices payload. The exact schema is provider-defined, so probe
    the common shapes; return (None, None) when nothing usable is found."""
    rows = None
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        for key in ("prices", "data", "results", "items"):
            if isinstance(payload.get(key), list):
                rows = payload[key]
                break
    if not rows:
        return None, None
    closes, volumes = [], []
    for row in rows:
        if not isinstance(row, dict):
            return None, None
        close = None
        for key in ("close", "adj_close", "adjClose", "c", "price"):
            if isinstance(row.get(key), (int, float)):
                close = float(row[key])
                break
        if close is None:
            return None, None
        closes.append(close)
        vol = row.get("volume", row.get("v"))
        volumes.append(float(vol) if isinstance(vol, (int, float)) else 0.0)
    return (closes, volumes) if len(closes) >= 30 else (None, None)

def _yahoo_chart(ticker: str):
    """Fallback price source (SOUL: Yahoo only when the AIsa call fails).
    Returns (closes, volumes) oldest→newest, or (None, None)."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           "?range=6mo&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.load(resp)
        node = payload["chart"]["result"][0]
        quote = node["indicators"]["quote"][0]
        pairs = [(c, v if isinstance(v, (int, float)) else 0.0)
                 for c, v in zip(quote["close"], quote["volume"])
                 if isinstance(c, (int, float))]
        if len(pairs) < 30:
            return None, None
        closes = [p[0] for p in pairs]
        volumes = [p[1] for p in pairs]
        return closes, volumes
    except Exception:
        return None, None

def _rsi14(closes: list) -> float | None:
    if len(closes) < 15:
        return None
    gains = losses = 0.0
    for prev, cur in zip(closes[-15:-1], closes[-14:]):
        delta = cur - prev
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    if losses == 0:
        return 100.0
    rs = (gains / 14) / (losses / 14)
    return round(100 - 100 / (1 + rs), 1)

def _compute_indicators(closes: list, volumes: list) -> dict:
    last = closes[-1]
    def pct(n):
        return (round((last / closes[-1 - n] - 1) * 100, 2)
                if len(closes) > n else None)
    sma = lambda n: (round(sum(closes[-n:]) / n, 2) if len(closes) >= n else None)
    return {
        "last_close": round(last, 2),
        "chg_1d_pct": pct(1),
        "chg_5d_pct": pct(5),
        "chg_20d_pct": pct(20),
        "sma20": sma(20),
        "sma50": sma(50),
        "rsi14": _rsi14(closes),
        "range_6mo_low": round(min(closes), 2),
        "range_6mo_high": round(max(closes), 2),
        "avg_volume_20d": int(sum(volumes[-20:]) / max(1, len(volumes[-20:]))),
        "last_volume": int(volumes[-1]),
        "sessions": len(closes),
    }

def _aisa_chat(system: str, user: str, timeout: int = 60) -> str:
    """One chat call to the AISA gateway (OpenAI-compatible). Returns the
    assistant text; raises RuntimeError with a short reason on failure."""
    api_key = _read_env_value(AISA_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"missing {AISA_API_KEY_ENV}")
    body = json.dumps({
        "model": QUICK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 700,
    }).encode("utf-8")
    req = urllib.request.Request(
        AISA_CHAT_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"gateway HTTP {e.code}") from e
    except Exception as e:
        raise RuntimeError(f"gateway unreachable: {e}") from e
    try:
        text = payload["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError) as e:
        raise RuntimeError("gateway returned an unexpected payload shape") from e
    if not text:
        raise RuntimeError("gateway returned an empty completion")
    return text

_QUICK_SYSTEM_PROMPT = """\
You are the quick-research arm of an AI Chief Investment Officer. Produce a
QUICK single-pass take in English on one stock, using ONLY the data provided
in the user message. Never invent prices, fundamentals, news, or analyst
views; if a field is missing, say "no data" instead of guessing. This is a
quick take, not full research — do not imply news/sentiment were reviewed.

Answer in exactly this structure, under 220 words total:
DECISION: <BUY | HOLD | TRIM | AVOID | WATCH> — one-line rationale
KEY POINTS:
- 3 to 5 bullets grounded in the provided data
KEY RISKS:
- 1 to 2 bullets
CONFIDENCE: <LOW | MEDIUM> — single-pass quick take on price/technicals/fundamentals only
"""

def run_quick_research(ticker: str) -> str:
    """Tier 1: synchronous quick take. Data pull + ONE flash LLM call.

    Prices come from marketpulse first (SOUL data-source priority), Yahoo as
    fallback. If BOTH fail the run fails — a take without real data would be
    fabrication. Returns 'DONE: ...\\n\\n<report>' or 'FAILED: ...'.
    """
    ticker = ticker.upper().strip()
    trade_date = date.today().isoformat()
    start = (date.today() - timedelta(days=186)).isoformat()

    closes = volumes = None
    price_source = None
    payload = _marketpulse(["prices", "--ticker", ticker,
                            "--start", start, "--end", trade_date])
    if payload is not None:
        closes, volumes = _extract_closes(payload)
        if closes:
            price_source = "marketpulse (AIsa)"
    if not closes:
        closes, volumes = _yahoo_chart(ticker)
        if closes:
            price_source = "Yahoo Finance (fallback)"
    if not closes:
        return (f"FAILED: no price data available for {ticker} from marketpulse "
                "or Yahoo — refusing to produce a take without real data.")

    indicators = _compute_indicators(closes, volumes)

    metrics_note = "no data"
    metrics = _marketpulse(["metrics", "--ticker", ticker])
    if metrics is not None:
        metrics_note = json.dumps(metrics, ensure_ascii=False)[:1500]

    user_msg = (
        f"Ticker: {ticker}\nDate: {trade_date}\n"
        f"Price source: {price_source}\n"
        f"Technical snapshot (computed from daily closes):\n"
        f"{json.dumps(indicators, ensure_ascii=False)}\n"
        f"Key fundamentals (marketpulse metrics, raw JSON, may be partial):\n"
        f"{metrics_note}\n"
    )

    try:
        take = _aisa_chat(_QUICK_SYSTEM_PROMPT, user_msg)
    except RuntimeError as e:
        return f"FAILED: quick-research LLM call failed ({e})."

    report = "\n".join([
        f"[{ticker}] Quick Research",
        f"Date: {trade_date}",
        "[QUICK MODE — single-pass quick take on price/technicals/fundamentals; "
        "NOT the multi-agent research; news/sentiment not consulted]",
        f"Price data: {price_source}",
        "",
        take,
        "",
        QUICK_TIP.format(ticker=ticker),
    ])

    result = {
        "success": True,
        "ticker": ticker,
        "trade_date": trade_date,
        "mode": "quick",
        "provider_used": "aisa-gateway",
        "model_used": QUICK_MODEL,
        "price_source": price_source,
        "report_text": report,
    }
    try:
        _cache_result(ticker, trade_date, result, "quick")
        report_path = _report_txt_path(ticker, trade_date, "quick")
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
    except Exception:
        pass  # cache failure is non-fatal; stdout still carries the report

    return f"DONE: {ticker} quick research complete.\n\n{report}"

# -- Core TA runner ------------------------------------------------------------

def _try_provider(provider: str, ticker: str, trade_date: str,
                  mode: str = "full") -> dict:
    """Run TradingAgents once with the given provider configuration.

    Returns a result dict with {"success": bool, ...}. The dict carries
    "provider_attempted" so caller can log which path was taken.
    """
    # TA_VENV_PYTHON alone is sufficient when the `ta` venv has the package
    # pip-installed (AgentSpec setup.python); TA_DIR remains a legacy fallback
    # for source-checkout installs.
    global TA_VENV_PYTHON
    if not TA_VENV_PYTHON:
        TA_VENV_PYTHON = _ensure_ta_env()   # lazy first-use provisioning
    if not TA_VENV_PYTHON:
        return {
            "success": False,
            "provider_attempted": provider,
            "error": (
                "TradingAgents is not installed and auto-provisioning failed "
                "(TA_VENV_PYTHON unresolved). Run `aisa agent install aisa-cio` "
                "without AGENT_SKIP_OPTIONAL_SETUP to build the `ta` venv from "
                "requirements/ta.txt, or set TA_VENV_PYTHON in the profile .env."
            ),
        }

    args = _build_runner_args(provider, ticker, trade_date, mode)
    if args is None:
        return {
            "success": False,
            "provider_attempted": provider,
            "error": f"missing API key for provider {provider}",
        }

    runner_code = RUNNER_TEMPLATE.format(**args)

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    try:
        tmp.write(runner_code)
        tmp.close()

        print(
            f"[{provider}] Starting TradingAgents ({mode} mode) for "
            f"{ticker.upper()} ({trade_date}) using {args['deep_think_llm']}...",
            flush=True,
        )
        proc = subprocess.run(
            [TA_VENV_PYTHON, tmp.name],
            capture_output=True,
            text=True,
            timeout=1800,   # 30 min — generous ceiling for long TA runs
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "provider_attempted": provider,
            "error": "TradingAgents timed out (1800 s).",
        }
    finally:
        os.unlink(tmp.name)

    if proc.returncode != 0:
        return {
            "success": False,
            "provider_attempted": provider,
            "error": "TradingAgents subprocess returned non-zero exit code.",
            "stderr": proc.stderr[-2000:],
        }

    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("__TA_RESULT__:"):
            try:
                result = json.loads(line[len("__TA_RESULT__:"):])
                result["provider_attempted"] = provider
                return result
            except json.JSONDecodeError as e:
                return {
                    "success": False,
                    "provider_attempted": provider,
                    "error": f"JSON parse error: {e}",
                    "raw": line[:500],
                }

    return {
        "success": False,
        "provider_attempted": provider,
        "error": "No __TA_RESULT__ marker found in TA output.",
        "stdout": proc.stdout[-2000:],
    }

def call_trading_agents_api(ticker: str, mode: str = "full") -> dict:
    """Run TradingAgents over PROVIDER_CHAIN, caching the first success.

    Full mode: the two entries are genuinely different configs (-pro then the
    lighter -flash), so the second attempt is a real fallback.

    Deep mode: both entries resolve to the SAME all-flash config, so the second
    attempt is a transient-failure RETRY rather than provider diversity. This is
    deliberate and empirically load-bearing — in the 2026-07-25 AAPL fast-mode
    verification the first attempt died on a non-deterministic subprocess
    failure and the identical retry completed the run. A retry succeeding on an
    unchanged config is itself evidence the failure class is transient, so
    dropping it would convert recoverable blips into hard failures. Cost when it
    does fire is one extra deep run (~3 min).
    """
    try:
        mode = _normalize_mode(mode)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    if mode == "quick":
        return {"success": False,
                "error": "quick mode is synchronous — call run_quick_research()."}
    trade_date = date.today().isoformat()
    last_failure: dict | None = None

    for provider in PROVIDER_CHAIN:
        result = _try_provider(provider, ticker, trade_date, mode)
        if result.get("success"):
            try:
                _cache_result(
                    ticker.upper(),
                    result.get("trade_date", trade_date),
                    result,
                    mode,
                )
            except Exception:
                pass  # cache failure is non-fatal
            return result
        # Log and try next provider. Include the stderr tail so transient
        # failures are diagnosable from the log without re-running.
        err = result.get("error", "unknown")
        detail = result.get("stderr") or result.get("stdout") or ""
        print(
            f"[{provider}] TradingAgents failed: {err[:200]} — "
            f"falling back to next provider in chain"
            + (f"\n[{provider}] stderr tail: {detail[-500:]}" if detail else ""),
            file=sys.stderr,
            flush=True,
        )
        last_failure = result

    # All providers failed
    return last_failure or {
        "success": False,
        "error": "All providers failed and no diagnostic captured.",
    }

# -- Formatting ----------------------------------------------------------------

def _s(ta: dict, field: str) -> str:
    v = ta.get(field, "")
    return str(v).strip() if v else "(no data)"

def _debate_readable(raw: str, spec: list) -> str:
    """Render a debate-state JSON string as labelled sections.

    ``spec`` is a list of (json_key, heading) pairs; keys that are missing or
    empty are skipped. Falls back to the raw string when it isn't the expected
    JSON dict — never worse than the old json.dumps passthrough."""
    try:
        state = json.loads(raw)
        assert isinstance(state, dict)
    except Exception:
        return raw.strip() or "(no data)"
    parts = []
    for key, heading in spec:
        val = str(state.get(key) or "").strip()
        if val:
            parts.append(f"--- {heading} ---\n\n{val}")
    return "\n\n".join(parts) if parts else "(no data)"

def _investment_debate_readable(raw: str) -> str:
    # Combined "history" is dropped: it duplicates the bull/bear transcripts.
    return _debate_readable(raw, [
        ("bull_history", "Bull arguments"),
        ("bear_history", "Bear arguments"),
        ("judge_decision", "Judge decision"),
    ])

def _risk_debate_readable(raw: str) -> str:
    return _debate_readable(raw, [
        ("risky_history", "Aggressive analyst"),
        ("safe_history", "Conservative analyst"),
        ("neutral_history", "Neutral analyst"),
        ("judge_decision", "Risk judge decision"),
    ])

def _header_lines(result: dict) -> list:
    ticker     = result.get("ticker", "")
    trade_date = result.get("trade_date", "")
    mode       = result.get("mode", "full")
    lines = [f"[{ticker}] TradingAgents Research", f"Date: {trade_date}"]
    if mode in ("deep", "fast"):   # "fast" may appear in pre-rename caches
        lines.append(
            "[DEEP RESEARCH — market + fundamentals analysts only; "
            "news/sentiment not consulted]"
        )
    return lines

def format_report_sections(result: dict) -> list:
    """Return the complete report as a list of section strings."""
    if not result.get("success"):
        err     = result.get("error", "Unknown error")
        details = result.get("stderr", result.get("stdout", ""))
        msg = f"TradingAgents failed: {err}"
        if details:
            msg += f"\n\n{details[:800]}"
        return [msg]

    ticker = result.get("ticker", "")
    mode   = result.get("mode", "full")
    ta     = result.get("ta_response", {})
    sep    = "=" * 22

    sections = [
        "\n".join([
            *_header_lines(result),
            "",
            sep, "1. FINAL DECISION", sep, "",
            _s(ta, "final_trade_decision"),
        ]),
        "\n".join([sep, "2. TRADING PLAN", sep, "", _s(ta, "trader_investment_plan")]),
        "\n".join([sep, "3. ANALYST DEBATE", sep, "",
                   _investment_debate_readable(ta.get("investment_debate_state", ""))]),
        "\n".join([sep, "4. RISK ASSESSMENT", sep, "",
                   _risk_debate_readable(ta.get("risk_debate_state", ""))]),
        "\n".join([
            sep, "5. ANALYST REPORTS", sep, "",
            "--- Market Report ---", "", _s(ta, "market_report"),
        ]),
    ]
    # Deep tier skips the analysts it never ran instead of printing "(no data)".
    if mode not in ("deep", "fast"):
        sections.append("\n".join(["--- Sentiment Report ---", "", _s(ta, "sentiment_report")]))
        sections.append("\n".join(["--- News Report ---", "", _s(ta, "news_report")]))
    sections.append("\n".join(["--- Fundamentals Report ---", "", _s(ta, "fundamentals_report")]))
    if mode in ("deep", "fast"):
        sections.append(FULL_REPORT_TIP.format(ticker=ticker))
    return sections

def format_brief_report(result: dict) -> str:
    """Deep-tier default output: decision + trading plan only (verbatim), plus
    the full-report tip. Debate/risk/analyst sections stay in the cached
    report.txt — they are on disk, not in the conversation context."""
    if not result.get("success"):
        return format_report_sections(result)[0]
    ticker = result.get("ticker", "")
    ta     = result.get("ta_response", {})
    sep    = "=" * 22
    return "\n\n".join([
        "\n".join([
            *_header_lines(result),
            "",
            sep, "1. FINAL DECISION", sep, "",
            _s(ta, "final_trade_decision"),
        ]),
        "\n".join([sep, "2. TRADING PLAN", sep, "", _s(ta, "trader_investment_plan")]),
        FULL_REPORT_TIP.format(ticker=ticker),
    ])

def format_full_report(result: dict) -> str:
    """Complete report as a single string."""
    return "\n\n".join(format_report_sections(result))

# -- Delivery pipeline ---------------------------------------------------------

def _report_txt_path(ticker: str, trade_date: str, mode: str = "full") -> str:
    return os.path.join(CACHE_DIR, ticker,
                        f"{trade_date}{_mode_suffix(mode)}-report.txt")

def run_and_report(ticker: str, resend: bool = False, mode: str = "full",
                   full_text: bool = False) -> str:
    """Run research (or load from cache with resend=True), then print a report.

    Returns a status line (DONE:/FAILED:) followed by the report body.
    Deep tier prints the BRIEF report unless ``full_text=True``; the complete
    deep output is always available in the cached report.txt. The Hermes agent
    reads stdout and delivers it over its own reply channel.
    """
    try:
        mode = _normalize_mode(mode)
    except ValueError as e:
        return f"FAILED: {e}"
    ticker = ticker.upper()
    trade_date = date.today().isoformat()

    if mode == "quick" and not resend:
        return run_quick_research(ticker)

    if resend:
        result = _load_cached_result(ticker, trade_date, mode)
        if not result:
            cache_path = os.path.join(
                CACHE_DIR, ticker,
                f"{trade_date}{_mode_suffix(mode)}-result.json")
            # If another tier has a cached report for today, say so — the run
            # was probably launched in that tier. Only hint when the file
            # really exists, so we never send the caller on a useless probe.
            hints = []
            for other in VALID_MODES:
                if other == mode:
                    continue
                other_path = os.path.join(
                    CACHE_DIR, ticker,
                    f"{trade_date}{_mode_suffix(other)}-result.json")
                if os.path.exists(other_path):
                    hints.append(f"A {other}-mode result DOES exist — retry "
                                 f"with mode={other!r}.")
            hint = (" " + " ".join(hints)) if hints else ""
            return (
                f"FAILED: No cached {mode}-mode result found for {ticker} on "
                f"{trade_date}. Expected at: {cache_path}. "
                f"Run without --resend first.{hint}"
            )
    else:
        result = call_trading_agents_api(ticker, mode)

    if not result.get("success"):
        return f"FAILED: {format_report_sections(result)[0][:300]}"

    # Quick-tier resend: the rendered report was cached verbatim.
    if mode == "quick":
        report = result.get("report_text", "").strip()
        if not report:
            return (f"FAILED: cached quick result for {ticker} has no report "
                    "text; launch a fresh `research` run.")
        return f"DONE: {ticker} quick research (cached).\n\n{report}"

    full_report = format_full_report(result)
    report_path = _report_txt_path(ticker, trade_date, mode)
    try:
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(full_report)
    except Exception:
        pass  # report-file write failure is non-fatal; stdout still carries it

    if mode == "deep" and not full_text:
        body = format_brief_report(result)
        return (
            f"DONE: {ticker} deep research complete (brief below; complete "
            f"deep output saved to {report_path}).\n\n{body}"
        )
    return (
        f"DONE: {ticker} research complete "
        f"(full report below; also saved to {report_path}).\n\n{full_report}"
    )

def run_in_background(ticker: str, mode: str = "full") -> str:
    """Launch deep/full research as a detached background process.

    Returns immediately with a STARTED: line (or FAILED: if the process could
    not be launched). Quick tier is synchronous — use run_quick_research().

    The background process calls run_and_report(); when finished (~3 min deep,
    ~9 min full) the result is cached under {CACHE_DIR}/<TICKER>/ and can be
    retrieved with --resend [--deep].
    """
    try:
        mode = _normalize_mode(mode)
    except ValueError as e:
        return f"FAILED: {e}"
    if mode == "quick":
        return ("FAILED: quick mode runs synchronously — call "
                "run_quick_research(ticker) instead of run_in_background().")
    ticker = ticker.upper()
    trade_date = date.today().isoformat()
    log_dir = os.environ.get("TA_LOG_DIR", os.path.expanduser("~/.tradingagents/logs"))
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{ticker}-{trade_date}{_mode_suffix(mode)}.log")

    eta = "~3 minutes" if mode == "deep" else "~9 minutes"
    resend_cmd = f"python3 {SCRIPT_PATH} {ticker} --resend" + (
        " --deep" if mode == "deep" else "")

    try:
        # sys.executable = hermes venv python3 (#4)
        # --background tells __main__ to call run_and_report() directly (no re-spawn)
        # start_new_session=True detaches from parent so execute_code can complete
        argv = [sys.executable, SCRIPT_PATH, ticker, "--background"]
        if mode == "deep":
            argv.append("--deep")
        with open(log_path, "w") as log_fh:
            proc = subprocess.Popen(
                argv,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return (
            f"STARTED: {ticker} {mode}-mode research launched in background "
            f"(PID {proc.pid}). It takes {eta}; the report will be cached at "
            f"{_report_txt_path(ticker, trade_date, mode)}. "
            f"Retrieve it when ready with: {resend_cmd} "
            f"(prints the report to stdout). Log: {log_path}."
        )
    except Exception as e:
        return f"FAILED: Could not start background process: {e}"

# -- CLI entry point -----------------------------------------------------------

if __name__ == "__main__":
    args          = sys.argv[1:]
    is_background = "--background" in args
    is_resend     = "--resend" in args
    is_full_text  = "--full-text" in args
    if "--quick" in args:
        mode = "quick"
    elif "--deep" in args or "--fast" in args:   # --fast: legacy alias
        mode = "deep"
    else:
        mode = "full"
    positional    = [a for a in args if not a.startswith("--")]
    ticker        = positional[0].upper() if positional else "NVDA"

    if mode == "quick" and not is_resend:
        # Quick tier is synchronous: run and print the report directly.
        print(run_quick_research(ticker))
    elif is_background or is_resend:
        # Called by the detached subprocess (output goes to the log file), or
        # by the agent retrieving a finished/cached report to stdout.
        print(run_and_report(ticker, resend=is_resend, mode=mode,
                             full_text=is_full_text))
    else:
        # Interactive / cron call: launch in background and return immediately.
        print(run_in_background(ticker, mode))
