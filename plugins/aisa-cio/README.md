# AIsa CIO

AI Chief Investment Officer — live multi-market portfolio valuation, stock research,
technical scans, and policy-driven allocation decisions. Covers US, HK, and JP equities,
plus ETFs, gold, bonds, money-market funds, and structured notes.

Responds in English.

## What it does

| Type this | You get |
|---|---|
| `portfolio` | Live portfolio valuation, priced at call time |
| `portfolio health` | Batch health check across every holding |
| `portfolio update` — or "I bought 100 shares of AAPL" | Guided holdings update, with confirmation and an automatic snapshot |
| `scan TICKER` | Single-stock technical quick-scan |
| `market brief US` | Index and sector overview for a market |
| `research TICKER` | Quick single-pass take (~1 min) |
| `deep-research TICKER` | Multi-agent research, market + fundamentals (~3 min) |
| `full-report TICKER` | Full multi-agent report, four analysts (~9 min) |
| `filings TICKER` | Primary-source SEC filings — 10-K/10-Q sections, statement notes, 13F, Form 4 |
| `help` | Onboarding and the full command list |

Natural language works too — "what does NVDA's latest 10-K say about risk?" routes to
the same place as `filings NVDA`.

## Operating rules

These are enforced in the agent's instructions, not left to judgement:

- **Never fabricates** prices, holdings, returns, filings, news, or analyst views. If live
  data is needed and unavailable, it says so instead of guessing.
- **Never trades.** It will not place, cancel, or simulate an order, and will not claim an
  order was placed.
- **Read-only on X/Twitter.** It reads timelines and trends; it never posts, likes, or follows.
- Separates **fact / assumption / analysis / recommendation** in every answer.
- Every recommendation carries its thesis, key risks, position sizing, portfolio impact,
  and an explicit call — buy, hold, trim, avoid, wait, or insufficient data.

> This agent is not a licensed financial adviser and its output is not investment advice.

## Setup

**Required**

| Variable | What it's for |
|---|---|
| `AISA_API_KEY` | The AIsa multi-model gateway — the default LLM plus the market-data, search, prediction-market, and social skills. Get one at <https://console.aisa.one/get-started> |

**Optional**

| Variable | What it unlocks | Without it |
|---|---|---|
| `SEC_IDENTITY` | Deep SEC filing research. Your own name and email, e.g. `Jane Doe jane@example.com` — the SEC requires every automated request to declare a real contact. Not an API key; there is nothing to sign up for | `filings` is unavailable; prices and quick financials still work |
| `AISA_MODEL` | The reasoning model used by the 30-day social scan | That one scan refuses to run; everything else is unaffected |

Put optional values in `~/.aisa/credentials` rather than a profile `.env` — that path
works in every distribution form, including this plugin.

## Python environments

Three optional virtualenvs are declared, each bootstrapped on first use by the skill that
needs it. All three are optional by design, and `portfolio` valuation is pure standard
library — it works with none of them installed.

| Name | Powers | Notes |
|---|---|---|
| `dsa` | `scan TICKER`, `market brief` | Light |
| `sec-filings` | `filings TICKER` | Free SEC data, no API key |
| `ta` | `deep-research`, `full-report` | Heavy install — skip it to keep setup light; the ~1 min `research` quick take does not need it |

## Data

Portfolio state lives in `~/.aisa/agents/aisa-cio/portfolio`, outside the plugin directory, and is seeded
on first use. Updates and reinstalls never overwrite it.

`portfolio_truth.json` ships as a sample portfolio. Replace it with your own holdings via
`portfolio update` before trusting any valuation — the agent will warn you while the
sample is still in place.

## License

MIT — see [LICENSE](LICENSE).

## Links

- [Agent page](https://aisa.one/agents/aisa-cio)
- [Privacy policy](https://aisa.one/privacy)
- [Terms of service](https://aisa.one/TOS)
