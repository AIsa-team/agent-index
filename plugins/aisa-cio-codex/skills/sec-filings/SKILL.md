---
name: sec-filings
description: "Deep SEC filing research — full 10-K/10-Q section text (Risk Factors, MD&A), structured financial-statement notes, in-filing BM25 search, full 13F institutional holdings tables, Form 4 insider transactions, market-wide filing scans (SC 13D). US-listed companies and ADRs only. Complements marketpulse, does not replace it."
metadata:
  version: "1.1.0"
  auto_invoke_on:
    - "读10-K"
    - "读10-Q"
    - "风险因素"
    - "Item 1A"
    - "MD&A"
    - "财报附注"
    - "13F 持仓明细"
    - "Form 4 明细"
    - "文件原文"
    - "filings TICKER"
  author: AIsa (vendored from dgunning/edgartools v5.43.0, MIT)
  tags:
    - sec
    - filings
    - 10-K
    - 10-Q
    - 13F
    - form-4
    - xbrl
    - fundamental-research
  platforms:
    - linux
    - macos
    - windows
---

> **Runtime bootstrap (sec-filings)** — this skill's scripts need a Python venv.
> Before first use (or if `${PLUGIN_ROOT}/.venvs/sec-filings/bin/python` is missing), run:
> `bash "${PLUGIN_ROOT}/scripts/ensure-venv.sh" sec-filings`
> Then invoke scripts with `${PLUGIN_ROOT}/.venvs/sec-filings/bin/python`. First run installs dependencies and can take a few minutes.

> **Required credentials** — scripts resolve these as: env var → `~/.aisa/credentials` (KEY=VALUE lines):
> - `SEC_IDENTITY` — Your own name + email, e.g. "Jane Doe jane@example.com". The SEC requires every automated request for filings to declare a real contact, and caps each declared identity at 10 requests/second. Not an API key — there is nothing to sign up for, and the value is sent verbatim without validation. Used only by the optional sec-filings skill. In a hermes/openclaw .env it MUST be quoted, since it contains spaces and the file is shell-sourced: SEC_IDENTITY="Jane Doe jane@example.com".
> If a value is missing, do NOT fail silently and do NOT just tell the user to "export" it.
> Guide them through setup right here in the conversation:
> 1. If they don't have the key, give them the sign-up link above and wait.
> 2. Ask them to paste the key into the chat, then save it for them:
>    `mkdir -p ~/.aisa && printf 'NAME=value\n' >> ~/.aisa/credentials && chmod 600 ~/.aisa/credentials`
>    (replace NAME=value with the real pair; keep one KEY=VALUE per line).
> 3. Immediately retry the user's original command — the file takes effect at once, no host restart needed.
> If the user prefers not to paste secrets into chat, offer the alternative: they export the
> env var themselves in the host's environment, then restart the host. 不要静默失败 / never fail silently.

# SEC Filings — Deep Filing Research

Pull primary-source data straight from SEC filings by writing Python against the
`edgartools` library. Free, no API key; SEC only requires an identity header.

## Routing — when to use this vs marketpulse

| Need | Use |
|---|---|
| Prices / OHLCV / quotes | **marketpulse** (this skill has NO price data) |
| Quick structured financials (revenue, margins) | **marketpulse first**; sec-filings as fallback |
| Full 10-K/10-Q **section text** (Item 1A Risk Factors, Item 7 MD&A) | **sec-filings** |
| Financial-statement **notes** (segment detail, acquisitions, debt footnotes) | **sec-filings** |
| Ranked **content search inside a filing** | **sec-filings** (`filing.search()`, BM25) |
| Full **13F infotable** as a DataFrame (every position) | **sec-filings** |
| **Market-wide filing scans** (all SC 13D activist stakes this quarter, all Form 4s) | **sec-filings** |
| HK / JP local-market stocks | **NEITHER** — SEC filings cover US filers + ADRs only (`BABA`, `TM` work; `9988.HK`, `7203.T` do not) |

For every row marked **sec-filings**, marketpulse is **not a substitute**. It
indexes filings but does not serve section text, and asked for a section it may
answer from a different, older filing. If this skill is unconfigured, fix the
configuration (see Setup) rather than swapping in a source that cannot answer the
question.

## Setup (once per session)

Runs in the optional `sec-filings` venv (managed by `setup.python`, pinned in
`requirements/sec-filings.txt`).

**Invoke it the same way the other optional venvs are invoked** — from
`execute_code`, via `subprocess.run` with an argument list. Do not build a shell
command line: filing code is full of quotes (`tenk['Item 1A']`), and passing a list
never goes through a shell, so nothing inside it can be re-interpreted.

```python
import subprocess, sys
CODE = r'''
import sys
sys.path.insert(0, "${PLUGIN_ROOT}/skills/sec-filings/scripts")
from sec_boot import boot
boot()
from edgar import Company, get_filings, find

filing = Company("NVDA").get_filings(form="10-K")[0]
print(filing.filing_date, filing.accession_no)
print(len(filing.obj()["Item 1A"]), "chars")
'''
r = subprocess.run(["${PLUGIN_ROOT}/.venvs/sec-filings/bin/python", "-c", CODE],
                   capture_output=True, text=True, timeout=900)
print(r.stdout)
sys.stderr.write(r.stderr)
```

The two fixed maintenance commands stay plain one-liners, since they take no
free-form code:

```bash
${PLUGIN_ROOT}/.venvs/sec-filings/bin/python ${PLUGIN_ROOT}/skills/sec-filings/scripts/sec_boot.py            # check config
${PLUGIN_ROOT}/.venvs/sec-filings/bin/python ${PLUGIN_ROOT}/skills/sec-filings/scripts/sec_boot.py --set "…"  # save identity
```

**The SEC requires every automated request to declare an identity** — undeclared
access is refused outright (HTTP 403). Their published format is
`Company Name AdminContact@yourdomain.com`. This agent reads it from the
`SEC_IDENTITY` environment variable, and sends whatever is there verbatim.

**Naming rule — applies to everything you say to the owner.** Call this **the SEC
identity**; call the source **SEC filings** or **the SEC's filing system**.
`SEC_IDENTITY` is a variable name — use it in code and file paths, not in prose.
Never write "EDGAR" or "EdgarTools" to the owner: `edgartools` is the pip package and
`edgar` its import path, and both stay inside code blocks. Filing URLs contain
`/Archives/edgar/` — cite them unchanged, but do not read the word out of them.

**The first three lines of `CODE` above are required every time.** `edgartools`
reads the contact from the process environment only, and only under its own
variable name, so one saved to `~/.aisa/credentials` or the profile `.env` would
otherwise be invisible. `boot()` resolves every sanctioned location, translates the
value into the name the library wants, and exits with setup guidance if nothing is
configured. Every pattern below assumes it has run.

Check configuration without a network call:

```bash
${PLUGIN_ROOT}/.venvs/sec-filings/bin/python ${PLUGIN_ROOT}/skills/sec-filings/scripts/sec_boot.py
```

A non-zero exit here means **not configured**, not "unavailable" — it prints the
exact command to fix it. Read that output and follow it; do not treat it as a
signal to go find another data source.

### When the identity is not configured

Do not make the owner edit a file. Complete the setup in the conversation:

1. **Ask them for it**, explaining what it is:
   > SEC requires every automated request to declare a real contact. This is not an
   > API key — there's nothing to sign up for. It's your own name and email, which
   > the SEC uses as the contact of record. What should I use?
2. **Save it for them** — one command, correct destination and quoting for this
   install form, idempotent, `chmod 600`:
   ```bash
   ${PLUGIN_ROOT}/.venvs/sec-filings/bin/python ${PLUGIN_ROOT}/skills/sec-filings/scripts/sec_boot.py --set "Their Name their@email.com"
   ```
3. **Retry the original request immediately.** It takes effect on the next call —
   no restart.

`--set` writes to the profile `.env` on hermes/openclaw installs (quoted, because
`.env` is shell-sourced and the value contains spaces) and to `~/.aisa/credentials`
on plugin installs (raw, because that file is parsed not sourced). Do not hand-write
either file — getting this wrong breaks profile rendering.

**Ask the owner what to declare — do not pick for them.** The value is stored and
sent verbatim; `--set` does not validate it, because the SEC does not check the
header either. What goes on the wire is the owner's decision.

Worth telling them once, then respecting whatever they choose: SEC's published
sample is `Company Name AdminContact@yourdomain.com`, and a reachable address is
what gets you a warning rather than a silent IP block if your traffic ever draws
attention.

**Do not route around an unconfigured identity.** Asking is the first move, not the
last resort. Specifically, when the identity is missing you must NOT quietly switch
to marketpulse, web search, or any other source and answer as if nothing
happened — a one-line setup question buys the owner the actual filing, and the
substitutes are not equivalent:

- marketpulse indexes filings but does not serve **section text**; asked for
  Item 1A it can return a *different, older* filing. Observed in testing: it
  answered from the prior year's 10-K (`…-25-000023`) while calling it the latest
  (the real one was `…-26-000021`) — a wrong answer delivered confidently.
- Web search returns commentary about filings, not the primary source, so nothing
  it produces can be attributed to the filing.

Only after the owner has been asked and declines or is genuinely unreachable may you
fall back — and then you must **say plainly that this is not the filing**, name the
source you actually used, and flag that the period may not match.

**Do not go looking for a credential on disk.** `sec_boot` already reads every
sanctioned location. Searching for `.env`, `.bak` or other backup files may surface a
value the owner deliberately removed, and using it decides something that is theirs
to decide.

Two preconditions, two different failures — do not confuse them:

| Missing | Meaning | What to tell the owner |
|---|---|---|
| the venv python shown above | optional `sec-filings` venv not installed | run the `sec-filings` setup/bootstrap step, or fall back to marketpulse |
| `SEC_IDENTITY` | SEC identity not configured | set it per the install-specific path above |

An unset identity is a configuration question for the owner, not a problem to route around.

## Core patterns (verified against v5.43.0, live SEC data 2026-07-25)

```python
# Universal lookup — ALWAYS the entry point for any identifier
c = find("NVDA")                       # ticker → Company
f = find("0001045810-26-000021")       # accession number → Filing

# Financials — use get_financials(), NOT filing.xbrl()
fin = Company("NVDA").get_financials()
rev = fin.get_revenue()                # latest annual revenue
inc = fin.income_statement()           # 3-year table w/ segment lines
# 4+ years: Company("NVDA").get_facts().income_statement(periods=5)

# 10-K sections — full primary-source text
filing = Company("NVDA").get_filings(form="10-K")[0]
tenk = filing.obj()
risk = tenk["Item 1A"]                 # Risk Factors, full text (~100k chars)
mda  = tenk["Item 7"]                  # MD&A

# Notes to financial statements — structured
tenk.notes.search("segment")           # fuzzy → ranked notes
tenk.notes["Debt"]                     # by title

# In-filing content search — BM25 ranked
results = filing.search("China export controls")
for i in range(min(5, len(results))):  # INDEX ONLY — see sharp edges
    m = results[i]
    print(m.score, str(m)[:200])

# 13F institutional holdings
f13 = Company("0001067983").get_filings(form="13F-HR")[0].obj()  # Berkshire
top = f13.infotable.nlargest(10, "Value")

# Form 4 insider transactions
for f in Company("NVDA").get_filings(form="4").head(5):
    print(f.filing_date, f.obj().insider_name)

# Market-wide scans
get_filings(form="SC 13D", year=2026, quarter=2)   # activist stakes
```

## Sharp edges (violating these causes real failures)

1. **`filing.search()` results do NOT support slicing** in v5.43.0 — `results[:5]`
   raises `TypeError` (upstream docs are wrong). Use integer indexing only.
2. **Run `boot()` before any data access** — never skip the preamble. Verified in
   v5.43.0: `Company("NVDA")` alone does *not* raise (construction is lazy); the
   failure surfaces on the first fetch. Worse, code paths reaching the library's own
   `get_identity()` print a setup panel and **block on stdin** (EOFError headless,
   up to a 60s hang on a TTY). A traceback, prompt, or panel mentioning
   `EDGAR_IDENTITY` means the preamble was skipped — re-run it, and never relay that
   variable name to the owner.
3. **Never iterate unbounded filings** — always `.head(N)` first.
4. **Respect 10 requests/second.** SEC policy: *"no more than 10 requests per second,
   regardless of the number of machines used to submit requests"* — the cap is per
   declared identity, and they enforce it by **blocking IP addresses**. Batch work,
   reuse results, do not parallelize scans across processes.
5. **HTTP 429** → stop, wait 10+ minutes; never retry immediately (risks an IP block).
6. First call in a session takes ~10s (ticker-map cache warm-up); subsequent calls
   are fast. Do not treat the first-call latency as a hang.
7. HK/JP local tickers raise `CompanyNotFoundError` — expected, route to
   marketpulse or say the data is out of scope.

## Reference material

**Read [`references/LOCAL_OVERRIDES.md`](references/LOCAL_OVERRIDES.md) first.** It is
short, and it lists the handful of upstream tips that are wrong for this pinned
version or superseded by this skill's setup flow — notably the `results[:5]` slicing
example, which raises `TypeError`. Where it and `upstream/` disagree, it wins.

`references/upstream/` then contains the vendored upstream skill (patterns, per-domain
sharp edges, API reference for Company/Filing/Statement/XBRL). Consult it for anything
beyond the core patterns above. Key files:

- `references/upstream/skill.yaml` — core patterns and API routing
- `references/upstream/sharp-edges.yaml` — upstream gotchas
- `references/upstream/financials|holdings|ownership|reports|xbrl/` — domain packs
- `references/upstream/api-reference/` — Company / Filing / Statement / XBRL docs

These are the library author's own docs, vendored verbatim and pinned so they stay
diffable against upstream. They use the library's house vocabulary — the product name
"EdgarTools", the `edgar` import path, the `EDGAR_IDENTITY` variable — and they predate
this skill's setup flow. Where they tell you to call `set_identity()` or to set
`EDGAR_IDENTITY`, the `sec_boot` preamble above overrides them. Use their code as
written; never carry their wording into what you say to the owner.

Vendored from edgartools **v5.43.0** (MIT). If the venv's installed version
diverges from 5.43.0, trust runtime behavior over these docs and note the mismatch.
