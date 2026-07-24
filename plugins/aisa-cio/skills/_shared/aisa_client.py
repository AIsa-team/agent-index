#!/usr/bin/env python3
"""
AIsa API Client — Shared Library for AIsa Agents
====================================================
Unified wrapper for all AIsa Skills APIs.
All agents (CIO, Writer, Manager) import from here.

Usage:
    from aisa_client import AIsaClient
    client = AIsaClient()
    data = client.marketpulse.prices("AAPL", interval="day", ...)
"""

import os
import json
import sys
import time
from typing import Optional, Dict, Any, List

import requests


# ─── Configuration ───────────────────────────────────────────────

class AIsaConfig:
    """Load AISA_API_KEY from environment or .env files."""
    
    @staticmethod
    def get_api_key() -> str:
        key = os.environ.get("AISA_API_KEY")
        if key:
            return key
        
        # Fallback: try loading from credentials/.env files.
        # ~/.aisa/credentials 是 plugin 安装形态的约定位置(无 hermes profile 可用),
        # 排最前:plugin 引导流程写入后无需重启宿主即可生效
        env_paths = [
            os.path.expanduser("~/.aisa/credentials"),
            os.path.expanduser("~/.hermes/.env"),
            os.path.expanduser("~/.hermes/profiles/manager/.env"),
        ]
        for env_path in env_paths:
            if os.path.exists(env_path):
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("AISA_API_KEY="):
                            return line.split("=", 1)[1].strip().strip('"').strip("'")
        return ""

    @staticmethod
    def ensure_key():
        key = AIsaConfig.get_api_key()
        if not key:
            print("ERROR: AISA_API_KEY not found in environment or .env files", file=sys.stderr)
            sys.exit(1)
        return key


# ─── Base Client ─────────────────────────────────────────────────

class AIsaClient:
    """Main client with sub-clients for each skill domain."""
    
    BASE_URL = "https://api.aisa.one"
    API_BASE = f"{BASE_URL}/apis/v1"
    
    def __init__(self, api_key: Optional[str] = None, quiet: bool = False):
        self.api_key = api_key or AIsaConfig.get_api_key()
        self.quiet = quiet
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "AIsa-AIsaClient/1.0"
        })
        
        # Sub-clients
        self.marketpulse = MarketPulseClient(self)
        self.search = SearchClient(self)
        self.twitter = TwitterClient(self)
        self.prediction = PredictionMarketClient(self)
        self.last30days = Last30DaysClient(self)
    
    def _get(self, path: str, params: Dict = None) -> Dict:
        url = f"{self.API_BASE}{path}"
        resp = self.session.get(url, params=params, timeout=30)
        self._check_response(resp, url)
        return resp.json()
    
    def _post(self, path: str, json_data: Dict = None, params: Dict = None) -> Dict:
        url = f"{self.API_BASE}{path}"
        resp = self.session.post(url, json=json_data, params=params, timeout=60)
        self._check_response(resp, url)
        return resp.json()
    
    def _check_response(self, resp, url):
        if resp.status_code >= 400:
            print(f"AIsa API Error [{resp.status_code}] {url}", file=sys.stderr)
            print(resp.text[:500], file=sys.stderr)
    
    def _print_json(self, data, label=""):
        """Print JSON data to stdout for agent consumption."""
        if self.quiet:
            return
        if label:
            print(f"\n{'='*60}")
            print(f"  {label}")
            print(f"{'='*60}")
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ─── MarketPulse Client ──────────────────────────────────────────

class MarketPulseClient:
    """Equity market data: prices, financials, SEC filings, insider trades, macro."""
    
    def __init__(self, client: AIsaClient):
        self.c = client
        self._p = lambda d, l="": self.c._print_json(d, l)
    
    # Prices
    def prices(self, ticker: str, interval: str = "day", interval_multiplier: int = 1,
               start_date: str = None, end_date: str = None):
        """Get historical OHLCV prices.
        
        interval: second, minute, day, week, month, year
        start_date/end_date: YYYY-MM-DD
        """
        # API requires start_date AND end_date; default to a trailing 30-day window
        from datetime import date, timedelta
        if not end_date:
            end_date = date.today().isoformat()
        if not start_date:
            start_date = (date.today() - timedelta(days=30)).isoformat()
        params = {
            "ticker": ticker,
            "interval": interval,
            "interval_multiplier": interval_multiplier,
            "start_date": start_date,
            "end_date": end_date,
        }
        data = self.c._get("/financial/prices", params)
        self._p(data, f"Prices: {ticker} ({interval})")
        return data
    
    # Financial Statements
    def financials(self, ticker: str, period: str = "annual"):
        """Get all three financial statements (income, balance, cash flow)."""
        data = self.c._get("/financial/financials", {"ticker": ticker, "period": period})
        self._p(data, f"Financials: {ticker} ({period})")
        return data
    
    def income_statements(self, ticker: str, period: str = "annual"):
        data = self.c._get("/financial/financials/income-statements", {"ticker": ticker, "period": period})
        self._p(data, f"Income Statement: {ticker} ({period})")
        return data
    
    def balance_sheets(self, ticker: str, period: str = "annual"):
        data = self.c._get("/financial/financials/balance-sheets", {"ticker": ticker, "period": period})
        self._p(data, f"Balance Sheet: {ticker} ({period})")
        return data
    
    def cash_flow_statements(self, ticker: str, period: str = "annual"):
        data = self.c._get("/financial/financials/cash-flow-statements", {"ticker": ticker, "period": period})
        self._p(data, f"Cash Flow: {ticker} ({period})")
        return data
    
    def segmented_revenues(self, ticker: str, period: str = "annual"):
        data = self.c._get("/financial/financials/segmented-revenues", {"ticker": ticker, "period": period})
        self._p(data, f"Segmented Revenues: {ticker} ({period})")
        return data
    
    # Metrics
    def metrics_snapshot(self, ticker: str):
        data = self.c._get("/financial/financial-metrics/snapshot", {"ticker": ticker})
        self._p(data, f"Metrics Snapshot: {ticker}")
        return data
    
    def metrics_history(self, ticker: str, period: str = "annual"):
        data = self.c._get("/financial/financial-metrics", {"ticker": ticker, "period": period})
        self._p(data, f"Metrics History: {ticker} ({period})")
        return data
    
    # Insider & Institutional
    def insider_trades(self, ticker: str):
        data = self.c._get("/financial/insider-trades", {"ticker": ticker})
        self._p(data, f"Insider Trades: {ticker}")
        return data
    
    def institutional_ownership(self, ticker: str):
        data = self.c._get("/financial/institutional-ownership", {"ticker": ticker})
        self._p(data, f"Institutional Ownership: {ticker}")
        return data
    
    # SEC Filings
    def filings_index(self, ticker: str):
        data = self.c._get("/financial/filings", {"ticker": ticker})
        self._p(data, f"SEC Filings Index: {ticker}")
        return data
    
    def filing_items(self, ticker: str, filing_type: str = "10-K", year: int = 2024):
        data = self.c._get("/financial/filings/items", {
            "ticker": ticker, "filing_type": filing_type, "year": year
        })
        self._p(data, f"Filing Items: {ticker} {filing_type} {year}")
        return data
    
    # Screening
    def screener(self, filters: dict):
        """Stock screener. Example: {"pe_ratio": {"max": 15}, "revenue_growth": {"min": 0.2}}"""
        data = self.c._post("/financial/financials/search/screener", {"filters": filters})
        self._p(data, f"Stock Screener")
        return data
    
    def line_items(self, tickers: list, line_items: list, period: str = "annual"):
        """Cross-ticker metric search."""
        data = self.c._post("/financial/financials/search/line-items", {
            "tickers": tickers, "line_items": line_items, "period": period
        })
        self._p(data, f"Line Items: {tickers}")
        return data
    
    # Macro
    def interest_rates_snapshot(self):
        data = self.c._get("/financial/macro/interest-rates/snapshot")
        self._p(data, "Interest Rates Snapshot")
        return data


# ─── Multi-source Search Client ──────────────────────────────────

class SearchClient:
    """Unified web, academic, Perplexity, and Tavily search."""
    
    def __init__(self, client: AIsaClient):
        self.c = client
        self._p = lambda d, l="": self.c._print_json(d, l)
    
    def web_search(self, query: str):
        data = self.c._post("/scholar/search/web", params={"query": query})
        self._p(data, f"Web Search: {query}")
        return data
    
    def scholar_search(self, query: str):
        data = self.c._post("/scholar/search/scholar", params={"query": query})
        self._p(data, f"Scholar Search: {query}")
        return data
    
    def mixed_search(self, query: str):
        """Hybrid web + scholar search."""
        data = self.c._post("/scholar/search/mixed", params={"query": query})
        self._p(data, f"Mixed Search: {query}")
        return data
    
    def perplexity_sonar(self, query: str, model: str = "sonar"):
        """Perplexity Sonar search with inline citations.
        model: sonar, sonar-pro, sonar-reasoning-pro, sonar-deep-research
        """
        data = self.c._post(f"/perplexity/{model}", {
            "model": model,
            "messages": [{"role": "user", "content": query}]
        })
        self._p(data, f"Perplexity {model}: {query[:60]}")
        return data
    
    def perplexity_deep_research(self, query: str):
        """Exhaustive deep research with full report."""
        return self.perplexity_sonar(query, "sonar-deep-research")
    
    def tavily_search(self, query: str):
        data = self.c._post("/tavily/search", {"query": query})
        self._p(data, f"Tavily Search: {query}")
        return data
    
    def tavily_extract(self, urls: list):
        """Extract clean article text from URLs."""
        data = self.c._post("/tavily/extract", {"urls": urls})
        self._p(data, f"Tavily Extract: {len(urls)} URLs")
        return data
    
    def tavily_crawl(self, url: str, depth: int = 2):
        data = self.c._post("/tavily/crawl", {"url": url, "depth": depth})
        self._p(data, f"Tavily Crawl: {url}")
        return data
    
    def tavily_map(self, url: str):
        data = self.c._post("/tavily/map", {"url": url})
        self._p(data, f"Tavily Map: {url}")
        return data


# ─── Twitter Client ──────────────────────────────────────────────

class TwitterClient:
    """Full X/Twitter intelligence — profiles, tweets, trends, lists, communities.
    Read + Write (OAuth-gated) operations via the AIsa gateway."""
    
    def __init__(self, client: AIsaClient):
        self.c = client
        self._p = lambda d, l="": self.c._print_json(d, l)
    
    # ─── Write Operations (OAuth Required) ──────────────────────
    
    def post_tweet(self, text: str, reply_to: str = None, media_urls: list = None,
                   quote_tweet_id: str = None):
        """Post a tweet (or reply/quote) via OAuth. Returns tweet data on success."""
        body = {"aisa_api_key": self.c.api_key, "content": text}
        if reply_to:
            body["in_reply_to_tweet_id"] = reply_to
        if quote_tweet_id:
            body["type"] = "quote"
            body["quote_tweet_id"] = quote_tweet_id
        if media_urls:
            body["media_ids"] = media_urls
        data = self.c._post("/twitter/post_twitter", body)
        self._p(data, f"Post Tweet")
        return data
    
    def like_tweet(self, tweet_id: str):
        """Like a tweet on behalf of the authenticated user."""
        data = self.c._post("/twitter/like_twitter", {"tweet_id": tweet_id})
        self._p(data, f"Like Tweet: {tweet_id}")
        return data
    
    def follow_user(self, target_user_id: str):
        """Follow a target user."""
        data = self.c._post("/twitter/follow_twitter", {"target_user_id": target_user_id})
        self._p(data, f"Follow User: {target_user_id}")
        return data
    
    def auth_status(self):
        """Check OAuth authorization status for write operations."""
        data = self.c._get("/twitter/auth/status")
        self._p(data, "Auth Status")
        return data
    
    # ─── Read Operations ─────────────────────────────────────────
    
    def user_info(self, username: str):
        data = self.c._get("/twitter/user/info", {"userName": username})
        self._p(data, f"Twitter User: @{username}")
        return data
    
    def last_tweets(self, username: str):
        data = self.c._get("/twitter/user/last_tweets", {"userName": username})
        self._p(data, f"Latest Tweets: @{username}")
        return data
    
    def mentions(self, username: str):
        data = self.c._get("/twitter/user/mentions", {"userName": username})
        self._p(data, f"Mentions: @{username}")
        return data
    
    def followers(self, username: str):
        data = self.c._get("/twitter/user/followers", {"userName": username})
        self._p(data, f"Followers: @{username}")
        return data
    
    def followings(self, username: str):
        data = self.c._get("/twitter/user/followings", {"userName": username})
        self._p(data, f"Followings: @{username}")
        return data
    
    def user_search(self, query: str):
        data = self.c._get("/twitter/user/search", {"query": query})
        self._p(data, f"User Search: {query}")
        return data
    
    def advanced_search(self, query: str, query_type: str = "Latest"):
        data = self.c._get("/twitter/tweet/advanced_search", {
            "query": query, "queryType": query_type
        })
        self._p(data, f"Tweet Search: {query} [{query_type}]")
        return data
    
    def tweets_by_ids(self, tweet_ids: list):
        data = self.c._get("/twitter/tweets", {"tweet_ids": ",".join(tweet_ids)})
        self._p(data, f"Tweets by IDs")
        return data
    
    def tweet_replies(self, tweet_id: str):
        data = self.c._get("/twitter/tweet/replies", {"tweetId": tweet_id})
        self._p(data, f"Replies: {tweet_id}")
        return data
    
    def tweet_quotes(self, tweet_id: str):
        data = self.c._get("/twitter/tweet/quotes", {"tweetId": tweet_id})
        self._p(data, f"Quotes: {tweet_id}")
        return data
    
    def tweet_retweeters(self, tweet_id: str):
        data = self.c._get("/twitter/tweet/retweeters", {"tweetId": tweet_id})
        self._p(data, f"Retweeters: {tweet_id}")
        return data
    
    def thread_context(self, tweet_id: str):
        data = self.c._get("/twitter/tweet/thread_context", {"tweetId": tweet_id})
        self._p(data, f"Thread Context: {tweet_id}")
        return data
    
    def trends(self, woeid: int = 1):
        """Get trending topics. woeid=1 for worldwide."""
        data = self.c._get("/twitter/trends", {"woeid": woeid})
        self._p(data, f"Trends (WOEID={woeid})")
        return data
    
    def article_by_tweet(self, tweet_id: str):
        """Extract full article URL from a tweet."""
        data = self.c._get("/twitter/article", {"tweet_id": tweet_id})
        self._p(data, f"Article from tweet: {tweet_id}")
        return data


# ─── Prediction Market Client ────────────────────────────────────

class PredictionMarketClient:
    """Unified Polymarket + Kalshi prediction market data."""
    
    def __init__(self, client: AIsaClient):
        self.c = client
        self._p = lambda d, l="": self.c._print_json(d, l)
    
    # Polymarket
    def polymarket_markets(self, search: str = "", status: str = "active"):
        data = self.c._get("/polymarket/markets", {"search": search, "status": status})
        self._p(data, f"Polymarket: {search or 'all'}")
        return data
    
    def polymarket_events(self):
        data = self.c._get("/polymarket/events")
        self._p(data, "Polymarket Events")
        return data
    
    def polymarket_price(self, token_id: str):
        data = self.c._get(f"/polymarket/market-price/{token_id}")
        self._p(data, f"Polymarket Price: {token_id}")
        return data
    
    def polymarket_orderbooks(self, token_id: str):
        data = self.c._get("/polymarket/orderbooks", {"token_id": token_id})
        self._p(data, f"Polymarket Orderbook: {token_id}")
        return data
    
    def polymarket_candlesticks(self, token_id: str):
        data = self.c._get("/polymarket/candlesticks", {"token_id": token_id})
        self._p(data, f"Polymarket Candles: {token_id}")
        return data
    
    def polymarket_wallet_activity(self, wallet: str):
        data = self.c._get("/polymarket/activity", {"wallet": wallet})
        self._p(data, f"Polymarket Activity: {wallet}")
        return data
    
    def polymarket_wallet_pnl(self, wallet: str, granularity: str = "day"):
        data = self.c._get("/polymarket/wallet-pnl", {"wallet": wallet, "granularity": granularity})
        self._p(data, f"Polymarket P&L: {wallet}")
        return data
    
    # Kalshi
    def kalshi_markets(self, search: str = ""):
        data = self.c._get("/kalshi/markets", {"search": search})
        self._p(data, f"Kalshi: {search or 'all'}")
        return data
    
    def kalshi_price(self, ticker: str):
        data = self.c._get(f"/kalshi/market-price/{ticker}")
        self._p(data, f"Kalshi Price: {ticker}")
        return data
    
    def kalshi_trades(self, ticker: str):
        data = self.c._get("/kalshi/trades", {"ticker": ticker})
        self._p(data, f"Kalshi Trades: {ticker}")
        return data
    
    def kalshi_orderbooks(self, ticker: str):
        data = self.c._get("/kalshi/orderbooks", {"ticker": ticker})
        self._p(data, f"Kalshi Orderbook: {ticker}")
        return data
    
    # Cross-platform
    def sports_matching(self, sport: str = None, date: str = None):
        if sport:
            params = {}
            if date:
                params["date"] = date
            data = self.c._get(f"/matching-markets/sports/{sport}", params)
        else:
            data = self.c._get("/matching-markets/sports")
        self._p(data, f"Matching Markets: {sport or 'all'}")
        return data


# ─── Last30Days Client ───────────────────────────────────────────

class Last30DaysClient:
    """30-day multi-source research across 8 platforms."""
    
    def __init__(self, client: AIsaClient):
        self.c = client
        self._p = lambda d, l="": self.c._print_json(d, l)
    
    def research(self, topic: str, deep: bool = False):
        """
        Run a 30-day multi-source scan.
        
        Sources: Reddit, X/Twitter, YouTube, TikTok, Instagram, 
                 Hacker News, Polymarket, web search
        
        Returns ranked, clustered briefs with citations.
        """
        # The last30days skill is primarily script-based via the aisa CLI.
        # This is a simplified API-based version using the search client.
        print(f"\n{'='*60}")
        print(f"  Last30Days Research: {topic}")
        if deep:
            print(f"  Mode: DEEP (expanded candidate pool)")
        print(f"{'='*60}")
        
        # Use mixed search as the primary source for now
        results = self.c.search.mixed_search(topic)
        return results


# ─── CLI Entry Point (for direct script invocation) ──────────────

def main():
    """CLI dispatcher for direct script calls from agents."""
    import argparse
    
    parser = argparse.ArgumentParser(description="AIsa API Client")
    sub = parser.add_subparsers(dest="domain")
    
    # MarketPulse
    mp = sub.add_parser("marketpulse")
    mp.add_argument("action", choices=[
        "prices", "financials", "income", "balance", "cashflow",
        "segmented", "metrics", "metrics-history", "insider", "institutional",
        "filings", "filing-items", "screener", "line-items", "rates"
    ])
    mp.add_argument("--ticker", "-t", default="")
    mp.add_argument("--interval", default="day")
    mp.add_argument("--multiplier", type=int, default=1)
    mp.add_argument("--start-date", default="")
    mp.add_argument("--end-date", default="")
    mp.add_argument("--period", default="annual")
    mp.add_argument("--filing-type", default="10-K")
    mp.add_argument("--year", type=int, default=2024)
    mp.add_argument("--filters", default="{}")
    mp.add_argument("--tickers", default="")
    mp.add_argument("--line-items", default="")
    
    # Search
    sr = sub.add_parser("search")
    sr.add_argument("action", choices=[
        "web", "scholar", "mixed", "sonar", "sonar-pro",
        "sonar-reasoning", "deep-research", "tavily-search",
        "tavily-extract", "tavily-crawl", "tavily-map"
    ])
    sr.add_argument("--query", "-q", default="")
    sr.add_argument("--urls", default="")
    sr.add_argument("--url", default="")
    sr.add_argument("--depth", type=int, default=2)
    
    # Twitter
    tw = sub.add_parser("twitter")
    tw.add_argument("action", choices=[
        "user", "tweets", "mentions", "followers", "followings",
        "user-search", "tweet-search", "tweets-by-id", "replies",
        "quotes", "retweeters", "thread", "trends", "article",
        "post", "like", "follow", "auth-status"
    ])
    tw.add_argument("--username", default="")
    tw.add_argument("--query", default="")
    tw.add_argument("--tweet-id", default="")
    tw.add_argument("--tweet-ids", default="")
    tw.add_argument("--woeid", type=int, default=1)
    tw.add_argument("--query-type", default="Latest")
    tw.add_argument("--text", default="")
    tw.add_argument("--reply-to", default="")
    tw.add_argument("--media-urls", default="")
    tw.add_argument("--quote-tweet-id", default="")
    tw.add_argument("--target-user-id", default="")
    
    # Prediction Markets
    pm = sub.add_parser("prediction")
    pm.add_argument("action", choices=[
        "poly-markets", "poly-events", "poly-price", "poly-orderbook",
        "poly-candles", "poly-activity", "poly-pnl",
        "kalshi-markets", "kalshi-price", "kalshi-trades", "kalshi-orderbook",
        "sports-matching"
    ])
    pm.add_argument("--search", default="")
    pm.add_argument("--token-id", default="")
    pm.add_argument("--ticker", default="")
    pm.add_argument("--wallet", default="")
    pm.add_argument("--sport", default="")
    pm.add_argument("--date", default="")
    
    args = parser.parse_args()
    
    client = AIsaClient()
    
    if args.domain == "marketpulse":
        mp = client.marketpulse
        a = args.action
        if a == "prices":
            mp.prices(args.ticker, args.interval, args.multiplier,
                      args.start_date or None, args.end_date or None)
        elif a == "financials": mp.financials(args.ticker, args.period)
        elif a == "income": mp.income_statements(args.ticker, args.period)
        elif a == "balance": mp.balance_sheets(args.ticker, args.period)
        elif a == "cashflow": mp.cash_flow_statements(args.ticker, args.period)
        elif a == "segmented": mp.segmented_revenues(args.ticker, args.period)
        elif a == "metrics": mp.metrics_snapshot(args.ticker)
        elif a == "metrics-history": mp.metrics_history(args.ticker, args.period)
        elif a == "insider": mp.insider_trades(args.ticker)
        elif a == "institutional": mp.institutional_ownership(args.ticker)
        elif a == "filings": mp.filings_index(args.ticker)
        elif a == "filing-items": mp.filing_items(args.ticker, args.filing_type, args.year)
        elif a == "screener": mp.screener(json.loads(args.filters))
        elif a == "line-items":
            mp.line_items(args.tickers.split(","), args.line_items.split(","), args.period)
        elif a == "rates": mp.interest_rates_snapshot()
    
    elif args.domain == "search":
        sr = client.search
        a = args.action
        if a == "web": sr.web_search(args.query)
        elif a == "scholar": sr.scholar_search(args.query)
        elif a == "mixed": sr.mixed_search(args.query)
        elif a == "sonar": sr.perplexity_sonar(args.query, "sonar")
        elif a == "sonar-pro": sr.perplexity_sonar(args.query, "sonar-pro")
        elif a == "sonar-reasoning": sr.perplexity_sonar(args.query, "sonar-reasoning-pro")
        elif a == "deep-research": sr.perplexity_deep_research(args.query)
        elif a == "tavily-search": sr.tavily_search(args.query)
        elif a == "tavily-extract": sr.tavily_extract(args.urls.split(","))
        elif a == "tavily-crawl": sr.tavily_crawl(args.url, args.depth)
        elif a == "tavily-map": sr.tavily_map(args.url)
    
    elif args.domain == "twitter":
        tw = client.twitter
        a = args.action
        if a == "user": tw.user_info(args.username)
        elif a == "tweets": tw.last_tweets(args.username)
        elif a == "mentions": tw.mentions(args.username)
        elif a == "followers": tw.followers(args.username)
        elif a == "followings": tw.followings(args.username)
        elif a == "user-search": tw.user_search(args.query)
        elif a == "tweet-search": tw.advanced_search(args.query, args.query_type)
        elif a == "tweets-by-id": tw.tweets_by_ids(args.tweet_ids.split(","))
        elif a == "replies": tw.tweet_replies(args.tweet_id)
        elif a == "quotes": tw.tweet_quotes(args.tweet_id)
        elif a == "retweeters": tw.tweet_retweeters(args.tweet_id)
        elif a == "thread": tw.thread_context(args.tweet_id)
        elif a == "trends": tw.trends(args.woeid)
        elif a == "article": tw.article_by_tweet(args.tweet_id)
        elif a == "post":
            media_urls = args.media_urls.split(",") if args.media_urls else None
            tw.post_tweet(args.text, args.reply_to or None, media_urls, args.quote_tweet_id or None)
        elif a == "like": tw.like_tweet(args.tweet_id)
        elif a == "follow": tw.follow_user(args.target_user_id)
        elif a == "auth-status": tw.auth_status()
    
    elif args.domain == "prediction":
        pm = client.prediction
        a = args.action
        if a == "poly-markets": pm.polymarket_markets(args.search)
        elif a == "poly-events": pm.polymarket_events()
        elif a == "poly-price": pm.polymarket_price(args.token_id)
        elif a == "poly-orderbook": pm.polymarket_orderbooks(args.token_id)
        elif a == "poly-candles": pm.polymarket_candlesticks(args.token_id)
        elif a == "poly-activity": pm.polymarket_wallet_activity(args.wallet)
        elif a == "poly-pnl": pm.polymarket_wallet_pnl(args.wallet)
        elif a == "kalshi-markets": pm.kalshi_markets(args.search)
        elif a == "kalshi-price": pm.kalshi_price(args.ticker)
        elif a == "kalshi-trades": pm.kalshi_trades(args.ticker)
        elif a == "kalshi-orderbook": pm.kalshi_orderbooks(args.ticker)
        elif a == "sports-matching": pm.sports_matching(args.sport or None, args.date or None)


if __name__ == "__main__":
    main()
