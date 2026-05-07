import time
import requests
import pandas as pd
from datetime import datetime

# ==========================================
# CONFIG
# ==========================================

TELEGRAM_BOT_TOKEN = "8628541851:AAGTo4LDtxv8WOy40L5YI7kqIdwv2SLNUKI"
TELEGRAM_CHAT_ID = "5067771509"

CHECK_INTERVAL = 180

# شرط الارتفاع خلال 24 ساعة
MIN_24H_PUMP = 50

# RSI
MIN_RSI = 80

# أقل سيولة
MIN_VOLUME_USDT = 500000

# ==========================================
# TELEGRAM
# ==========================================

def send_telegram(message):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        requests.post(url, data=data, timeout=10)

    except Exception as e:
        print("Telegram Error:", e)

# ==========================================
# RSI
# ==========================================

def calculate_rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)

    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()

    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss

    rsi = 100 - (100 / (1 + rs))

    return rsi

# ==========================================
# GET KLINES
# ==========================================

def get_klines(symbol, interval="5m", limit=100):

    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={symbol}&interval={interval}&limit={limit}"
    )

    response = requests.get(url, timeout=20)

    data = response.json()

    df = pd.DataFrame(data, columns=[
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "qav",
        "trades",
        "tbav",
        "tqav",
        "ignore"
    ])

    cols = ["open", "high", "low", "close", "volume"]

    for col in cols:
        df[col] = pd.to_numeric(df[col])

    return df

# ==========================================
# PRICE CHANGE
# ==========================================

def calculate_change(df):

    first = df["close"].iloc[0]

    last = df["close"].iloc[-1]

    if first == 0:
        return 0

    return ((last - first) / first) * 100

# ==========================================
# LONG UPPER WICK
# ==========================================

def has_long_upper_wick(df):

    candle = df.iloc[-1]

    body = abs(candle["close"] - candle["open"])

    upper_wick = candle["high"] - max(
        candle["open"],
        candle["close"]
    )

    if body == 0:
        body = 0.0001

    ratio = upper_wick / body

    return ratio >= 2

# ==========================================
# WEAK VOLUME
# ==========================================

def weak_volume(df):

    recent = df["volume"].tail(3).mean()

    previous = df["volume"].tail(10).head(7).mean()

    return recent < previous

# ==========================================
# GET 24H GAINERS
# ==========================================

def get_candidates():

    url = "https://api.binance.com/api/v3/ticker/24hr"

    response = requests.get(url, timeout=20)

    data = response.json()

    results = []

    for coin in data:

        try:

            symbol = coin["symbol"]

            if not symbol.endswith("USDT"):
                continue

            change_24h = float(
                coin["priceChangePercent"]
            )

            volume = float(
                coin["quoteVolume"]
            )

            if (
                change_24h >= MIN_24H_PUMP
                and volume >= MIN_VOLUME_USDT
            ):

                results.append({
                    "symbol": symbol,
                    "change_24h": change_24h,
                    "volume": volume
                })

        except:
            pass

    return sorted(
        results,
        key=lambda x: x["change_24h"],
        reverse=True
    )

# ==========================================
# ANALYZE
# ==========================================

def analyze(symbol):

    try:

        # 5m
        df_5m = get_klines(symbol, "5m", 100)

        # 15m
        df_15m = get_klines(symbol, "15m", 100)

        # 1h
        df_1h = get_klines(symbol, "1h", 100)

        # 4h
        df_4h = get_klines(symbol, "4h", 100)

        # 1d
        df_1d = get_klines(symbol, "1d", 4)

        # RSI
        df_5m["RSI"] = calculate_rsi(
            df_5m["close"]
        )

        rsi = float(
            df_5m["RSI"].iloc[-1]
        )

        # WICK
        wick_5m = has_long_upper_wick(df_5m)

        wick_15m = has_long_upper_wick(df_15m)

        wick = wick_5m or wick_15m

        # VOLUME
        volume_is_weak = weak_volume(df_5m)

        # CHANGES
        change_1h = calculate_change(
            df_1h.tail(2)
        )

        change_4h = calculate_change(
            df_4h.tail(2)
        )

        change_3d = calculate_change(
            df_1d
        )

        signal = (
            rsi >= MIN_RSI
            and wick
            and volume_is_weak
        )

        return {
            "signal": signal,
            "rsi": rsi,
            "wick": wick,
            "weak_volume": volume_is_weak,
            "change_1h": change_1h,
            "change_4h": change_4h,
            "change_3d": change_3d
        }

    except Exception as e:

        print("Analyze Error:", symbol, e)

        return None

# ==========================================
# MAIN
# ==========================================

already_sent = set()

print("BOT STARTED")

send_telegram(
    "🚀 <b>Scalping Reversal Bot Started</b>"
)

while True:

    try:

        candidates = get_candidates()

        print("Candidates:", len(candidates))

        for coin in candidates:

            symbol = coin["symbol"]

            if symbol in already_sent:
                continue

            result = analyze(symbol)

            if not result:
                continue

            if result["signal"]:

                message = f"""
🚨 <b>SHORT SIGNAL</b>

💰 <b>{symbol}</b>

📈 24H Pump:
<b>{coin['change_24h']:.2f}%</b>

📈 Last 3 Days:
<b>{result['change_3d']:.2f}%</b>

📈 Last 4 Hours:
<b>{result['change_4h']:.2f}%</b>

📈 Last 1 Hour:
<b>{result['change_1h']:.2f}%</b>

━━━━━━━━━━━━━━

📊 RSI 5M:
<b>{result['rsi']:.2f}</b>

🕯 Long Upper Wick:
<b>{result['wick']}</b>

📉 Weak Volume:
<b>{result['weak_volume']}</b>

━━━━━━━━━━━━━━

💵 Entry: <b>5$</b>
⚡ Leverage: <b>2x Isolated</b>

🎯 Target:
<b>1$ Profit</b>

🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

                print(message)

                send_telegram(message)

                already_sent.add(symbol)

    except Exception as e:

        print("MAIN ERROR:", e)

    time.sleep(CHECK_INTERVAL)
