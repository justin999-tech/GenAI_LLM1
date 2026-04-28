"""Stock and crypto price tools (free APIs)."""
import json
import urllib.parse
import urllib.request


def _http(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Lab2-Chatbot/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def crypto_price(symbol: str, currency: str = "usd") -> str:
    """Get crypto price from CoinGecko (no key needed)."""
    try:
        # Map common symbols → CoinGecko IDs
        mapping = {
            "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
            "doge": "dogecoin", "ada": "cardano", "xrp": "ripple",
            "bnb": "binancecoin", "matic": "matic-network",
            "dot": "polkadot", "avax": "avalanche-2",
        }
        sym = symbol.strip().lower()
        coin_id = mapping.get(sym, sym)
        url = ("https://api.coingecko.com/api/v3/simple/price?"
               + urllib.parse.urlencode({
                   "ids": coin_id,
                   "vs_currencies": currency.lower(),
                   "include_24hr_change": "true",
                   "include_market_cap": "true",
               }))
        data = json.loads(_http(url))
        if coin_id not in data:
            return f"Unknown symbol: {symbol}. Try BTC, ETH, SOL, etc."
        d = data[coin_id]
        cur = currency.lower()
        price = d.get(cur)
        change = d.get(f"{cur}_24h_change", 0)
        mcap = d.get(f"{cur}_market_cap", 0)
        arrow = "📈" if change >= 0 else "📉"
        return (f"{symbol.upper()} ({coin_id}): "
                f"{currency.upper()} {price:,.2f} {arrow} {change:+.2f}% (24h)\n"
                f"Market cap: {currency.upper()} {mcap:,.0f}")
    except Exception as e:
        return f"Crypto price lookup failed: {e}"


def stock_price(ticker: str) -> str:
    """Get stock price from Yahoo Finance public quote API (no key needed)."""
    try:
        # Yahoo Finance v7 quote endpoint
        url = (f"https://query1.finance.yahoo.com/v7/finance/quote?"
               + urllib.parse.urlencode({"symbols": ticker.upper()}))
        try:
            data = json.loads(_http(url, timeout=15))
        except Exception:
            # Fallback to chart endpoint
            return _stock_via_chart(ticker)
        results = data.get("quoteResponse", {}).get("result", [])
        if not results:
            return _stock_via_chart(ticker)
        q = results[0]
        price = q.get("regularMarketPrice")
        change = q.get("regularMarketChange", 0)
        change_pct = q.get("regularMarketChangePercent", 0)
        currency = q.get("currency", "USD")
        name = q.get("longName") or q.get("shortName") or ticker.upper()
        arrow = "📈" if change >= 0 else "📉"
        return (f"{ticker.upper()} ({name}): "
                f"{currency} {price:,.2f} {arrow} {change:+.2f} ({change_pct:+.2f}%)")
    except Exception as e:
        return f"Stock lookup failed: {e}"


def _stock_via_chart(ticker: str) -> str:
    try:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}?"
               "interval=1d&range=5d")
        data = json.loads(_http(url, timeout=15))
        result = data.get("chart", {}).get("result", [])
        if not result:
            return f"No data for {ticker}"
        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        prev = meta.get("previousClose", price)
        currency = meta.get("currency", "USD")
        change = (price - prev) if (price and prev) else 0
        pct = (change / prev * 100) if prev else 0
        arrow = "📈" if change >= 0 else "📉"
        return (f"{ticker.upper()}: {currency} {price:,.2f} "
                f"{arrow} {change:+.2f} ({pct:+.2f}%)")
    except Exception as e:
        return f"Stock chart lookup failed: {e}"


TOOLS = {
    "crypto_price": {
        "description": "Get current crypto price (BTC, ETH, SOL, DOGE, etc.) via CoinGecko.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "currency": {"type": "string", "default": "usd"},
            },
            "required": ["symbol"],
        },
        "handler": lambda a: crypto_price(a.get("symbol", ""), a.get("currency", "usd")),
    },
    "stock_price": {
        "description": "Get current stock price via Yahoo Finance. Use ticker like 'AAPL', '2330.TW'.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
        "handler": lambda a: stock_price(a.get("ticker", "")),
    },
}
