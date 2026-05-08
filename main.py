import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime

# =========================================================
# CONFIG
# =========================================================

TELEGRAM_TOKEN = "8628541851:AAGTo4LDtxv8WOy40L5YI7kqIdwv2SLNUKI"

CHAT_IDS = [
    "5067771509",
    "2107567005"
]

INTERVAL = 180

MIN_PUMP = 10
MIN_VOLUME = 200000

# =========================================================
# TELEGRAM
# =========================================================

def send(msg):

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    for chat in CHAT_IDS:

        try:
            response = requests.post(
                url,
                data={
                    "chat_id": chat,
                    "text": msg,
                    "parse_mode": "HTML"
                },
                timeout=10
            )
            print(f"Sent to {chat}: {response.status_code}")

        except Exception as e:
            print(f"Error sending to {chat}: {e}")

# =========================================================
# INDICATORS
# =========================================================

def rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def ema(series, period=20):

    return series.ewm(span=period, adjust=False).mean()

# =========================================================
# BINANCE DATA
# =========================================================

def klines(symbol):

    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit=200"

    data = requests.get(url).json()

    df = pd.DataFrame(data)

    df = df.iloc[:, :6]

    df.columns = ["t","o","h","l","c","v"]

    for col in ["o","h","l","c","v"]:
        df[col] = pd.to_numeric(df[col])

    return df

# =========================================================
# FILTER COINS
# =========================================================

def binance_scan():

    url = "https://api.binance.com/api/v3/ticker/24hr"

    data = requests.get(url).json()

    out = []

    for c in data:

        try:

            sym = c["symbol"]

            if not sym.endswith("USDT"):
                continue

            pump = float(c["priceChangePercent"])
            vol = float(c["quoteVolume"])

            if pump > MIN_PUMP and vol > MIN_VOLUME:

                out.append({
                    "symbol": sym,
                    "pump": pump,
                    "exchange": "BINANCE"
                })

        except:
            continue

    return out

# =========================================================
# PATTERNS
# =========================================================

def wick(df):

    c = df.iloc[-1]

    body = abs(c["c"] - c["o"])
    upper = c["h"] - max(c["c"], c["o"])

    if body == 0:
        body = 0.001

    return upper / body > 2


def volume_weak(df):

    return df["v"].tail(3).mean() < df["v"].tail(15).mean()


def bearish(df):

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    return (
        prev["c"] > prev["o"]
        and curr["c"] < curr["o"]
        and curr["o"] > prev["c"]
    )

# =========================================================
# ANALYZE
# =========================================================

def analyze(symbol, pump):

    df = klines(symbol)

    price = df["c"].iloc[-1]

    df["rsi"] = rsi(df["c"])
    df["ema"] = ema(df["c"])

    r = df["rsi"].iloc[-1]
    ema20 = df["ema"].iloc[-1]

    stretch = ((price - ema20) / ema20) * 100

    score = 0

    if r > 65:
        score += 20

    if r > 75:
        score += 10

    if stretch > 5:
        score += 10

    if wick(df):
        score += 15

    if volume_weak(df):
        score += 15

    if bearish(df):
        score += 20

    entry_low = price * 1.01
    entry_high = price * 1.03

    drop = stretch * 0.7
    
    # إضافة بيانات إضافية للرسالة
    rsi_5m = r
    rsi_15m = df["rsi"].iloc[-3] if len(df) >= 3 else r
    rsi_1h = df["rsi"].iloc[-12] if len(df) >= 12 else r
    
    change_24h = pump
    change_4h = ((df["c"].iloc[-1] / df["c"].iloc[-48]) - 1) * 100 if len(df) >= 48 else pump
    change_1h = ((df["c"].iloc[-1] / df["c"].iloc[-12]) - 1) * 100 if len(df) >= 12 else pump

    return {
        "score": score,
        "price": price,
        "rsi": r,
        "stretch": stretch,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "drop": drop,
        "rsi_5m": rsi_5m,
        "rsi_15m": rsi_15m,
        "rsi_1h": rsi_1h,
        "change_24h": change_24h,
        "change_4h": change_4h,
        "change_1h": change_1h
    }

# =========================================================
# MAIN LOOP
# =========================================================

sent = set()

print("STARTED V3 SCANNER")

send("🚀 V3 MULTI SIGNAL SCANNER STARTED")

while True:

    try:

        coins = binance_scan()
        print(f"Found {len(coins)} coins meeting criteria")

        for c in coins:

            sym = c["symbol"]

            uid = sym

            if uid in sent:
                continue

            res = analyze(sym, c["pump"])

            if not res:
                continue

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

            # تصحيح الرسالة - استخدام المتغيرات الصحيحة
            message = f"""
{color} BINANCE — {grade}

━━━━━━━━━━━━━━━━━━
🔥 SHORT OPPORTUNITY
━━━━━━━━━━━━━━━━━━

💰 PAIR: {sym}
🧠 AI SCORE: {score} / 100
⚠️ SIGNAL STRENGTH: {grade}

━━━━━━━━━━━━━━━━━━
📊 MARKET MOVEMENT
━━━━━━━━━━━━━━━━━━

📈 24H CHANGE: {res['change_24h']:.2f}%
⏱ 4H CHANGE: {res['change_4h']:.2f}%
⚡ 1H CHANGE: {res['change_1h']:.2f}%

━━━━━━━━━━━━━━━━━━
🧠 TECHNICAL ANALYSIS
━━━━━━━━━━━━━━━━━━

📊 RSI 5M: {res['rsi_5m']:.2f}
📊 RSI 15M: {res['rsi_15m']:.2f}
📊 RSI 1H: {res['rsi_1h']:.2f}

🕯 CANDLE PATTERN:
✔ Bearish Rejection

📉 VOLUME STATUS:
⚠ Weakening

📏 EMA DISTANCE:
{res['stretch']:.2f}%

━━━━━━━━━━━━━━━━━━
🎯 TRADE SETUP
━━━━━━━━━━━━━━━━━━

🔴 SHORT ENTRY ZONE:
{res['entry_low']:.8f} → {res['entry_high']:.8f}

📉 EXPECTED DROP:
{res['drop']:.2f}%

━━━━━━━━━━━━━━━━━━
💼 RISK MANAGEMENT
━━━━━━━━━━━━━━━━━━

💵 POSITION SIZE: 5$
⚡ LEVERAGE: x2 (Isolated)

━━━━━━━━━━━━━━━━━━
⏱ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
━━━━━━━━━━━━━━━━━━
"""

            print(message)
            send(message)

            sent.add(uid)
            
        time.sleep(INTERVAL)

    except Exception as e:
        print("ERROR:", e)
        time.sleep(INTERVAL)
