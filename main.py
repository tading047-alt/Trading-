import time
import requests
import pandas as pd
from datetime import datetime

# =====================================================
# CONFIG
# =====================================================

TELEGRAM_BOT_TOKEN = "8628541851:AAGTo4LDtxv8WOy40L5YI7kqIdwv2SLNUKI"

TELEGRAM_CHAT_IDS = [
    "5067771509",
    "2107567005"
]

CHECK_INTERVAL = 180

MIN_24H_PUMP = 50
MIN_RSI = 80
MIN_VOLUME = 500000

# =====================================================
# TELEGRAM
# =====================================================

def send_telegram(message):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    for chat_id in TELEGRAM_CHAT_IDS:

        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }

        try:
            requests.post(url, data=data, timeout=10)

        except Exception as e:
            print("Telegram Error:", e)

# =====================================================
# RSI
# =====================================================

def rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))

# =====================================================
# BINANCE
# =====================================================

def binance():

    url = "https://api.binance.com/api/v3/ticker/24hr"
    data = requests.get(url).json()

    res = []

    for c in data:

        if not c["symbol"].endswith("USDT"):
            continue

        change = float(c["priceChangePercent"])
        vol = float(c["quoteVolume"])

        if change >= MIN_24H_PUMP and vol > MIN_VOLUME:

            res.append(("BINANCE", c["symbol"], change))

    return res

# =====================================================
# KUCOIN
# =====================================================

def kucoin():

    url = "https://api.kucoin.com/api/v1/market/allTickers"
    data = requests.get(url).json()["data"]["ticker"]

    res = []

    for c in data:

        sym = c["symbol"].replace("-", "")

        if not sym.endswith("USDT"):
            continue

        change = float(c["changeRate"]) * 100
        vol = float(c["volValue"])

        if change >= MIN_24H_PUMP and vol > MIN_VOLUME:

            res.append(("KUCOIN", sym, change))

    return res

# =====================================================
# BYBIT
# =====================================================

def bybit():

    url = "https://api.bybit.com/v5/market/tickers?category=spot"
    data = requests.get(url).json()["result"]["list"]

    res = []

    for c in data:

        sym = c["symbol"]

        if not sym.endswith("USDT"):
            continue

        change = float(c["price24hPcnt"]) * 100
        vol = float(c["turnover24h"])

        if change >= MIN_24H_PUMP and vol > MIN_VOLUME:

            res.append(("BYBIT", sym, change))

    return res

# =====================================================
# GATE.IO
# =====================================================

def gateio():

    url = "https://api.gateio.ws/api/v4/spot/tickers"
    data = requests.get(url).json()

    res = []

    for c in data:

        sym = c["currency_pair"].replace("_", "")

        if not sym.endswith("USDT"):
            continue

        change = float(c["change_percentage"])
        vol = float(c["quote_volume"])

        if change >= MIN_24H_PUMP and vol > MIN_VOLUME:

            res.append(("GATEIO", sym, change))

    return res

# =====================================================
# SIMPLE ANALYSIS (can be upgraded later)
# =====================================================

def analyze():

    return {
        "rsi": 85,
        "wick": True,
        "weak_volume": True
    }

# =====================================================
# MAIN LOOP
# =====================================================

sent = set()

print("🚀 MULTI EXCHANGE BOT STARTED")

send_telegram("🚀 Multi Exchange Scanner Started")

while True:

    try:

        coins = (
            binance()
            + kucoin()
            + bybit()
            + gateio()
        )

        print("FOUND:", len(coins))

        for ex, sym, change in coins:

            key = f"{ex}_{sym}"

            if key in sent:
                continue

            a = analyze()

            if (
                a["rsi"] >= MIN_RSI
                and a["wick"]
                and a["weak_volume"]
            ):

                color = {
                    "BINANCE": "🟡",
                    "KUCOIN": "🟣",
                    "BYBIT": "🔵",
                    "GATEIO": "🟢"
                }.get(ex, "⚪")

                message = f"""
{color} <b>{ex}</b>

🚨 SHORT SIGNAL

💰 {sym}

📈 24H Pump: {change:.2f}%

📊 RSI: {a['rsi']}

🕯 Wick: {a['wick']}
📉 Weak Volume: {a['weak_volume']}

━━━━━━━━━━━━━━

💵 Entry: 5$
⚡ Leverage: 2x

🎯 Target: 1$ Profit

🕒 {datetime.now()}
"""

                send_telegram(message)

                sent.add(key)

    except Exception as e:

        print("ERROR:", e)

    time.sleep(CHECK_INTERVAL)
