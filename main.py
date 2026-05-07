import time
import requests
import pandas as pd
from datetime import datetime

# =========================================================
# CONFIG
# =========================================================

TOKEN = "8628541851:AAGTo4LDtxv8WOy40L5YI7kqIdwv2SLNUKI"

CHAT_IDS = [
    "5067771509",
    "-1003692815602"
]

INTERVAL = 180

# خلفيات المنصات
PLATFORM_BG = {
    "BINANCE": "https://i.imgur.com/binance_bg.jpg",
    "BYBIT": "https://i.imgur.com/bybit_bg.jpg",
    "KUCOIN": "https://i.imgur.com/kucoin_bg.jpg",
    "GATEIO": "https://i.imgur.com/gate_bg.jpg"
}

# =========================================================
# TELEGRAM SEND PHOTO
# =========================================================

def send_photo(chat_id, image, caption):

    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"

    requests.post(url, data={
        "chat_id": chat_id,
        "photo": image,
        "caption": caption,
        "parse_mode": "HTML"
    })

# =========================================================
# SEND ALERT
# =========================================================

def send(exchange, caption):

    img = PLATFORM_BG.get(exchange)

    for chat in CHAT_IDS:

        if img:
            send_photo(chat, img, caption)
        else:
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                data={
                    "chat_id": chat,
                    "text": caption,
                    "parse_mode": "HTML"
                }
            )

# =========================================================
# RSI
# =========================================================

def rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))

# =========================================================
# EMA
# =========================================================

def ema(series, period=20):
    return series.ewm(span=period).mean()

# =========================================================
# BINANCE DATA
# =========================================================

def klines(symbol):

    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit=120"

    data = requests.get(url).json()

    df = pd.DataFrame(data)

    df = df.iloc[:, :6]

    df.columns = ["t","o","h","l","c","v"]

    for c in ["o","h","l","c","v"]:
        df[c] = pd.to_numeric(df[c])

    return df

# =========================================================
# SCAN MARKET
# =========================================================

def scan():

    url = "https://api.binance.com/api/v3/ticker/24hr"

    data = requests.get(url).json()

    coins = []

    for c in data:

        try:

            sym = c["symbol"]

            if not sym.endswith("USDT"):
                continue

            pump = float(c["priceChangePercent"])
            vol = float(c["quoteVolume"])

            if pump > 10 and vol > 200000:

                coins.append({
                    "symbol": sym,
                    "pump": pump,
                    "exchange": "BINANCE"
                })

        except:
            continue

    return coins

# =========================================================
# ANALYSIS
# =========================================================

def analyze(symbol):

    df = klines(symbol)

    price = df["c"].iloc[-1]

    df["rsi"] = rsi(df["c"])
    df["ema"] = ema(df["c"])

    r = df["rsi"].iloc[-1]
    e = df["ema"].iloc[-1]

    stretch = ((price - e) / e) * 100

    score = 0

    if r > 65:
        score += 20
    if r > 75:
        score += 15
    if stretch > 5:
        score += 10

    return {
        "score": score,
        "rsi": r,
        "stretch": stretch
    }

# =========================================================
# MAIN LOOP
# =========================================================

sent = set()

print("🚀 BOT STARTED")

while True:

    try:

        coins = scan()

        for c in coins:

            sym = c["symbol"]

            if sym in sent:
                continue

            res = analyze(sym)

            score = res["score"]

            # =================================================
            # GRADE SYSTEM
            # =================================================

            if score >= 85:
                grade = "🟢 VERY GOOD"
                prob = "HIGH"
                color = "🟢"

            elif score >= 70:
                grade = "🟡 GOOD"
                prob = "MEDIUM"
                color = "🟡"

            elif score >= 55:
                grade = "🔴 MEDIUM"
                prob = "LOW"
                color = "🔴"

            else:
                continue

            # =================================================
            # FINAL ALERT UI
            # =================================================

            caption = f"""
🔥 <b>ELITE SHORT SIGNAL</b>

💰 <b>{sym}</b>
🧠 AI SCORE: <b>{score}/100</b>
{color} {grade}

━━━━━━━━━━━━━━
📊 RSI: {res['rsi']:.2f}
📏 EMA STRETCH: {res['stretch']:.2f}%

━━━━━━━━━━━━━━
🎯 ENTRY:
Market Zone Detected

📉 EXPECTED DROP:
Auto-calculated

━━━━━━━━━━━━━━
⚡ PROBABILITY: {prob}
💵 POSITION: 5$ | x2 LEVERAGE

⏱ {datetime.now()}
"""

            print(caption)

            send(c["exchange"], caption)

            sent.add(sym)

    except Exception as e:
        print("ERROR:", e)

    time.sleep(INTERVAL)
