from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
from datetime import datetime
import os

app = FastAPI(title="Signal IA Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "CG-oYuNa2mRPwLcZSBVSVxNXLeu")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "af04f67aed154ea8821513f17a4f8d6a")

COIN_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana"
}

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    gains, losses = 0, 0
    for i in range(1, period + 1):
        d = prices[i] - prices[i-1]
        if d > 0: gains += d
        else: losses += abs(d)
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(prices)):
        d = prices[i] - prices[i-1]
        avg_gain = (avg_gain * (period-1) + (d if d > 0 else 0)) / period
        avg_loss = (avg_loss * (period-1) + (abs(d) if d < 0 else 0)) / period
    if avg_loss == 0:
        return 100
    return round(100 - 100 / (1 + avg_gain / avg_loss), 1)

def calc_ma(prices, period):
    slc = prices[-min(period, len(prices)):]
    return sum(slc) / len(slc)

def calc_macd(prices):
    if len(prices) < 26:
        return prices[-1] > prices[0]
    k12, k26 = 2/13, 2/27
    e12, e26 = prices[0], prices[0]
    for p in prices[1:]:
        e12 = p * k12 + e12 * (1 - k12)
        e26 = p * k26 + e26 * (1 - k26)
    return e12 > e26

def calc_volatility(prices):
    returns = [(prices[i]-prices[i-1])/prices[i-1]*100 for i in range(1, len(prices))]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean)**2 for r in returns) / len(returns)
    return round(variance**0.5, 2)

async def fetch_crypto_data(coin_id, currency="eur"):
    async with httpx.AsyncClient(timeout=10) as client:
        market_url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency={currency}&ids={coin_id}&price_change_percentage=1h,7d&x_cg_demo_api_key={COINGECKO_API_KEY}"
        hist_url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency={currency}&days=30&interval=daily&x_cg_demo_api_key={COINGECKO_API_KEY}"
        
        market_res = await client.get(market_url)
        hist_res = await client.get(hist_url)
        
        market = market_res.json()[0]
        hist = hist_res.json()
        return market, hist

async def fetch_news(query):
    async with httpx.AsyncClient(timeout=10) as client:
        url = f"https://newsapi.org/v2/everything?q={query}&language=fr&pageSize=6&sortBy=publishedAt&apiKey={NEWS_API_KEY}"
        res = await client.get(url)
        data = res.json()
        if data.get("articles"):
            return [{"titre": a["title"], "source": a["source"]["name"]} for a in data["articles"][:6]]
        url_en = f"https://newsapi.org/v2/everything?q={query}&language=en&pageSize=6&sortBy=publishedAt&apiKey={NEWS_API_KEY}"
        res = await client.get(url_en)
        data = res.json()
        return [{"titre": a["title"], "source": a["source"]["name"]} for a in data.get("articles", [])[:6]]

def analyze_sentiment(titre):
    titre_lower = titre.lower()
    positive_words = ["record", "hausse", "bull", "pump", "surge", "rise", "gain", "approve", "adopt", "buy", "partnership", "launch", "growth", "high", "positive", "increase", "boost", "rally", "approval", "etf"]
    negative_words = ["chute", "bear", "dump", "crash", "fall", "ban", "hack", "fraud", "investigation", "regulation", "restriction", "low", "negative", "decrease", "loss", "sell", "warning", "risk", "concern", "drop"]
    
    score = 0
    for word in positive_words:
        if word in titre_lower:
            score += 1
    for word in negative_words:
        if word in titre_lower:
            score -= 1
    
    score = max(-2, min(2, score))
    impact = "POSITIF" if score > 0 else "NEGATIF" if score < 0 else "NEUTRE"
    return score, impact

@app.get("/")
async def root():
    return {"status": "Signal IA Backend en ligne", "timestamp": datetime.now().isoformat()}

@app.get("/api/crypto/{symbol}")
async def get_crypto(symbol: str, currency: str = "eur"):
    symbol = symbol.upper()
    if symbol not in COIN_IDS:
        return {"error": f"Symbole {symbol} non supporté"}
    
    try:
        coin_id = COIN_IDS[symbol]
        market, hist = await fetch_crypto_data(coin_id, currency)
        prices = [p[1] for p in hist["prices"]]
        
        current_price = market["current_price"]
        ch24h = market.get("price_change_percentage_24h", 0) or 0
        ch1h = market.get("price_change_percentage_1h_in_currency", 0) or 0
        ch7d = market.get("price_change_percentage_7d_in_currency", 0) or 0
        
        rsi = calc_rsi(prices)
        ma7 = calc_ma(prices, 7)
        ma14 = calc_ma(prices, 14)
        macd_bull = calc_macd(prices)
        volatility = calc_volatility(prices[-14:])
        volume = market.get("total_volume", 0)
        market_cap = market.get("market_cap", 1)
        
        bull = 0
        if rsi < 30: bull += 2
        elif rsi > 70: bull -= 2
        elif rsi > 50: bull += 1
        else: bull -= 1
        
        if current_price > ma7 and ma7 > ma14: bull += 2
        elif current_price < ma7 and ma7 < ma14: bull -= 2
        
        if macd_bull: bull += 1
        else: bull -= 1
        
        abs_bull = abs(bull)
        
        dir1h = "HAUSSE" if ch1h > 0.5 else "BAISSE" if ch1h < -0.5 else ("HAUSSE" if bull > 0 else "BAISSE" if bull < 0 else "STABLE")
        dir24h = "HAUSSE" if bull >= 2 else "BAISSE" if bull <= -2 else "STABLE"
        dir7d = "HAUSSE" if (current_price > ma14 and macd_bull) else "BAISSE" if (current_price < ma14 and not macd_bull) else "STABLE"
        
        sentiment_global = "BULLISH" if bull > 1 else "BEARISH" if bull < -1 else "NEUTRAL"
        score_sentiment = round(bull * 0.4, 1)
        
        news = await fetch_news(f"bitcoin {symbol}" if symbol == "BTC" else f"{symbol} crypto")
        analyzed_news = []
        total_sentiment = 0
        for n in news:
            score, impact = analyze_sentiment(n["titre"])
            analyzed_news.append({**n, "score": score, "impact": impact})
            total_sentiment += score
        
        if analyzed_news:
            news_sentiment = total_sentiment / len(analyzed_news)
            if news_sentiment > 0.3: 
                sentiment_global = "BULLISH"
                score_sentiment = min(2, score_sentiment + 0.3)
            elif news_sentiment < -0.3: 
                sentiment_global = "BEARISH"
                score_sentiment = max(-2, score_sentiment - 0.3)
        
        return {
            "symbol": symbol,
            "currency": currency,
            "price": current_price,
            "change_24h": round(ch24h, 2),
            "change_1h": round(ch1h, 2),
            "change_7d": round(ch7d, 2),
            "market_cap": market_cap,
            "volume_24h": volume,
            "ath": market.get("ath", 0),
            "indicators": {
                "rsi": rsi,
                "ma7": round(ma7, 2),
                "ma14": round(ma14, 2),
                "macd": "POSITIF" if macd_bull else "NEGATIF",
                "volatility": volatility,
                "bull_score": bull
            },
            "sentiment": {
                "global": sentiment_global,
                "score": score_sentiment
            },
            "predictions": {
                "1h": {"direction": dir1h, "amplitude": round(volatility * 0.15, 2), "confiance": min(50 + abs_bull * 5, 87)},
                "24h": {"direction": dir24h, "amplitude": round(volatility * 0.6, 2), "confiance": min(50 + abs_bull * 6, 84)},
                "1sem": {"direction": dir7d, "amplitude": round(volatility * 2.1, 2), "confiance": min(50 + abs_bull * 4, 79)}
            },
            "news": analyzed_news,
            "updated_at": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol}

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}
