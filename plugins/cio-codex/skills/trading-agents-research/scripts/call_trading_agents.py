"""
call_trading_agents.py
Calls the real TradingAgents multi-agent framework (not an LLM simulation).
Uses $TA_VENV_PYTHON (set in .env) via subprocess.

Delivery: results are cached to ~/.tradingagents/results/<TICKER>/ (raw JSON
+ formatted report.txt) and the full report is printed to stdout on --resend;
the Hermes agent relays it over its own reply channel. No direct
chat-platform API calls.

Optimisations (2026-04-26):
  #4  python3: background subprocess uses sys.executable (hermes venv python3)
  #7  Result cached to ~/.tradingagents/results/<TICKER>/<date>-result.json
      (+ <date>-report.txt); --resend re-prints without re-running TA
  #9  run_in_background() launches TA as a detached subprocess and returns
      immediately with STARTED: so the LLM conversation is never blocked
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date

AISA_API_KEY_ENV  = "AISA_API_KEY"
GEMINI_API_KEY_ENV   = "GEMINI_API_KEY"
GOOGLE_API_KEY_ENV   = "GOOGLE_API_KEY"
CACHE_DIR         = os.environ.get("TA_CACHE_DIR", os.path.expanduser("~/.tradingagents/results"))

# Resolve this script's own path early (works both when imported via importlib
# and run directly); the profile dir is derived from it so config discovery
# works even when the gateway does not export the profile .env into os.environ.
try:
    SCRIPT_PATH = os.path.realpath(__file__)
except NameError:
    SCRIPT_PATH = os.path.realpath(os.path.join(os.path.dirname(__file__), "call_trading_agents.py"))

# <profile>/skills/trading-agents-research/scripts/call_trading_agents.py -> <profile>
_PROFILE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_PATH))))

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

ta = TradingAgentsGraph(debug=False, config=config)
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


def _build_runner_args(provider: str, ticker: str, trade_date: str) -> dict | None:
    """Resolve provider-specific args for RUNNER_TEMPLATE.

    Returns a dict suitable for ``RUNNER_TEMPLATE.format(**args)`` or None if
    the required API key is missing for this provider.
    """
    common = dict(ta_dir=TA_DIR, ticker=ticker.upper(), trade_date=trade_date)

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
            "deep_think_llm":      "deepseek-v4-pro",
            "quick_think_llm":     "deepseek-v4-flash",
            # upstream openai_client requires DEEPSEEK_API_KEY for provider=deepseek
            "extra_env_lines":     'os.environ["DEEPSEEK_API_KEY"] = ' + repr(api_key),
            "thinking_config_line": "# DeepSeek V4 family always reasons; OpenAIClient disables in-history reasoning_content via extra_body",
        }

    if provider == "deepseek_flash":
        # In-family fallback: same provider, lighter model. Used by T3 only —
        # Gemini free tier can't sustain TA's 30+ call workload, so the safer
        # fallback is the lighter DeepSeek model (no separate quota).
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

def _cache_result(ticker: str, trade_date: str, result: dict) -> str:
    """Persist result dict to ~/.tradingagents/results/<TICKER>/<date>-result.json.

    Returns the cache file path.  Non-fatal: caller should catch exceptions.
    """
    cache_dir = os.path.join(CACHE_DIR, ticker)
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{trade_date}-result.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path


def _load_cached_result(ticker: str, trade_date: str) -> dict | None:
    """Load cached result for ticker/date, or return None if not found."""
    path = os.path.join(CACHE_DIR, ticker, f"{trade_date}-result.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


# -- Core TA runner ------------------------------------------------------------

def _try_provider(provider: str, ticker: str, trade_date: str) -> dict:
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
                "(TA_VENV_PYTHON unresolved). Run `aisa agent install cio` "
                "without AGENT_SKIP_OPTIONAL_SETUP to build the `ta` venv from "
                "requirements/ta.txt, or set TA_VENV_PYTHON in the profile .env."
            ),
        }

    args = _build_runner_args(provider, ticker, trade_date)
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
            f"[{provider}] Starting TradingAgents for {ticker.upper()} "
            f"({trade_date}) using {args['deep_think_llm']}...",
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


def call_trading_agents_api(ticker: str) -> dict:
    """Run TradingAgents with provider fallback chain.

    Tier 2 routing: try Gemini-2.5-flash:thinking first; on failure (transient
    503, library error, missing key, etc.) retry the entire run with
    DeepSeek-v4-flash. Caches the first successful result and returns it.

    Note: process-level fallback means a Gemini failure mid-run causes a full
    DeepSeek re-run from scratch (extra ~15 min). Acceptable for resilience
    against rare hard outages; transient mid-stream errors should be handled
    by langchain's built-in per-call retry.
    """
    trade_date = date.today().isoformat()
    last_failure: dict | None = None

    for provider in PROVIDER_CHAIN:
        result = _try_provider(provider, ticker, trade_date)
        if result.get("success"):
            try:
                _cache_result(
                    ticker.upper(),
                    result.get("trade_date", trade_date),
                    result,
                )
            except Exception:
                pass  # cache failure is non-fatal
            return result
        # Log and try next provider
        err = result.get("error", "unknown")
        print(
            f"[{provider}] TradingAgents failed: {err[:200]} — "
            f"falling back to next provider in chain",
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
    return str(v).strip() if v else "(无数据)"


def format_report_sections(result: dict) -> list:
    """Return the report as a list of section strings."""
    if not result.get("success"):
        err     = result.get("error", "Unknown error")
        details = result.get("stderr", result.get("stdout", ""))
        msg = f"TradingAgents failed: {err}"
        if details:
            msg += f"\n\n{details[:800]}"
        return [msg]

    ticker     = result.get("ticker", "")
    trade_date = result.get("trade_date", "")
    ta         = result.get("ta_response", {})
    sep        = "=" * 22

    return [
        "\n".join([
            f"[{ticker}] TradingAgents Research",
            f"Date: {trade_date}",
            "",
            sep, "1. FINAL DECISION", sep, "",
            _s(ta, "final_trade_decision"),
        ]),
        "\n".join([sep, "2. TRADING PLAN", sep, "", _s(ta, "trader_investment_plan")]),
        "\n".join([sep, "3. ANALYST DEBATE", sep, "", _s(ta, "investment_debate_state")]),
        "\n".join([sep, "4. RISK ASSESSMENT", sep, "", _s(ta, "risk_debate_state")]),
        "\n".join([
            sep, "5. ANALYST REPORTS", sep, "",
            "--- Market Report ---", "", _s(ta, "market_report"),
        ]),
        "\n".join(["--- Sentiment Report ---", "", _s(ta, "sentiment_report")]),
        "\n".join(["--- News Report ---", "", _s(ta, "news_report")]),
        "\n".join(["--- Fundamentals Report ---", "", _s(ta, "fundamentals_report")]),
    ]


def format_full_report(result: dict) -> str:
    """Full report as a single string."""
    return "\n\n".join(format_report_sections(result))


# -- Delivery pipeline ---------------------------------------------------------

def _report_txt_path(ticker: str, trade_date: str) -> str:
    return os.path.join(CACHE_DIR, ticker, f"{trade_date}-report.txt")


def run_and_report(ticker: str, resend: bool = False) -> str:
    """Run TA (or load from cache with resend=True), then print the report.

    Returns a status line (DONE:/FAILED:) followed by the full report body.
    The Hermes agent reads it from stdout and delivers it over its own
    reply channel.
    """
    ticker = ticker.upper()
    trade_date = date.today().isoformat()

    if resend:
        result = _load_cached_result(ticker, trade_date)
        if not result:
            cache_path = os.path.join(CACHE_DIR, ticker, f"{trade_date}-result.json")
            return (
                f"FAILED: No cached result found for {ticker} on {trade_date}. "
                f"Expected at: {cache_path}. Run without --resend first."
            )
    else:
        result = call_trading_agents_api(ticker)

    sections = format_report_sections(result)

    if not result.get("success"):
        return f"FAILED: {sections[0][:300]}"

    report = "\n\n".join(sections)
    report_path = _report_txt_path(ticker, trade_date)
    try:
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
    except Exception:
        pass  # report-file write failure is non-fatal; stdout still carries it

    return (
        f"DONE: {ticker} research complete "
        f"(full report below; also saved to {report_path}).\n\n{report}"
    )


def run_in_background(ticker: str) -> str:
    """Launch TA research as a detached background process. Returns immediately.

    The background process calls run_and_report(); when finished
    (~15-20 minutes) the result is cached under {CACHE_DIR}/<TICKER>/ and can
    be retrieved with --resend (prints the full report to stdout).

    Returns a STARTED: status line (or FAILED: if the process could not be launched).
    """
    ticker = ticker.upper()
    trade_date = date.today().isoformat()
    log_dir = os.environ.get("TA_LOG_DIR", os.path.expanduser("~/.tradingagents/logs"))
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{ticker}-{trade_date}.log")

    try:
        # sys.executable = hermes venv python3 (#4)
        # --background tells __main__ to call run_and_report() directly (no re-spawn)
        # start_new_session=True detaches from parent so execute_code can complete
        with open(log_path, "w") as log_fh:
            proc = subprocess.Popen(
                [sys.executable, SCRIPT_PATH, ticker, "--background"],
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return (
            f"STARTED: {ticker} research launched in background (PID {proc.pid}). "
            f"It takes ~15-20 minutes; the report will be cached at "
            f"{_report_txt_path(ticker, trade_date)}. "
            f"Retrieve it when ready with: python3 {SCRIPT_PATH} {ticker} --resend "
            f"(prints the full report to stdout). Log: {log_path}."
        )
    except Exception as e:
        return f"FAILED: Could not start background process: {e}"


# -- CLI entry point -----------------------------------------------------------

if __name__ == "__main__":
    args         = sys.argv[1:]
    is_background = "--background" in args
    is_resend     = "--resend" in args
    positional    = [a for a in args if not a.startswith("--")]
    ticker        = positional[0].upper() if positional else "NVDA"

    if is_background or is_resend:
        # Called by the detached subprocess (output goes to the log file), or
        # by the agent retrieving a finished/cached report to stdout.
        print(run_and_report(ticker, resend=is_resend))
    else:
        # Interactive / cron call: launch in background and return immediately.
        print(run_in_background(ticker))
