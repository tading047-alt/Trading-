import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime

# =========================================================
# CONFIG
# =========================================================

TELEGRAM_BOT_TOKEN = "8628541851:AAGTo4LDtxv8WOy40L5YI7kqIdwv2SLNUKI"

TELEGRAM_CHAT_IDS = [
    "5067771509",
    "FRIEND_CHAT_ID"
]

CHECK_INTERVAL = 180

MIN_24H_PUMP = 15
MIN_VOLUME = 300000

# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    for chat_id in TELEGRAM_CHAT_IDS:

        try:

            requests.post(
                url,
                data={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML"
                },
                timeout=10
            )

        except Exception as e:

            print("Telegram Error:", e)

# =========================================================
# RSI
# =========================================================

def calculate_rsi(series, period=14):

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
# ATR
# =========================================================

def atr(df, period=14):

    high_low = df["high"] - df["low"]

    high_close = np.abs(
        df["high"] - df["close"].shift()
    )

    low_close = np.abs(
        df["low"] - df["close"].shift()
    )

    ranges = pd.concat(
        [high_low, high_close, low_close],
        axis=1
    )

    true_range = np.max(ranges, axis=1)

    return pd.Series(true_range).rolling(period).mean()

# =========================================================
# FILTER TOKENS
# =========================================================

def valid_symbol(symbol):

    blocked = [
        "3L",
        "3S",
        "5L",
        "5S",
        "BULL",
        "BEAR"
    ]

    return not any(x in symbol for x in blocked)

# =========================================================
# BINANCE KLINES
# =========================================================

def get_binance_klines(symbol, interval="5m", limit=200):

    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={symbol}"
        f"&interval={interval}"
        f"&limit={limit}"
    )

    data = requests.get(url, timeout=20).json()

    df = pd.DataFrame(data)

    df = df.iloc[:, :6]

    df.columns = [
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume"
    ]

    cols = [
        "open",
        "high",
        "low",
        "close",
        "volume"
    ]

    for col in cols:

        df[col] = pd.to_numeric(df[col])

    return df

# =========================================================
# KUCOIN KLINES
# =========================================================

def get_kucoin_klines(symbol, interval="5min"):

    pair = symbol.replace("USDT", "-USDT")

    url = (
        f"https://api.kucoin.com/api/v1/market/candles"
        f"?type={interval}"
        f"&symbol={pair}"
    )

    data = requests.get(url, timeout=20).json()["data"]

    rows = []

    for r in reversed(data):

        rows.append({
            "open": float(r[1]),
            "close": float(r[2]),
            "high": float(r[3]),
            "low": float(r[4]),
            "volume": float(r[5])
        })

    return pd.DataFrame(rows)

# =========================================================
# BYBIT KLINES
# =========================================================

def get_bybit_klines(symbol, interval="5", limit=200):

    url = (
        f"https://api.bybit.com/v5/market/kline"
        f"?category=spot"
        f"&symbol={symbol}"
        f"&interval={interval}"
        f"&limit={limit}"
    )

    data = requests.get(url, timeout=20).json()

    rows = data["result"]["list"]

    result = []

    for r in reversed(rows):

        result.append({
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[5])
        })

    return pd.DataFrame(result)

# =========================================================
# GATEIO KLINES
# =========================================================

def get_gateio_klines(symbol, interval="5m", limit=200):

    pair = symbol.replace("USDT", "_USDT")

    url = (
        f"https://api.gateio.ws/api/v4/spot/candlesticks"
        f"?currency_pair={pair}"
        f"&interval={interval}"
        f"&limit={limit}"
    )

    data = requests.get(url, timeout=20).json()

    rows = []

    for r in reversed(data):

        rows.append({
            "open": float(r[5]),
            "high": float(r[3]),
            "low": float(r[4]),
            "close": float(r[2]),
            "volume": float(r[1])
        })

    return pd.DataFrame(rows)

# =========================================================
# GET CANDIDATES
# =========================================================

def get_binance():

    url = "https://api.binance.com/api/v3/ticker/24hr"

    data = requests.get(url, timeout=20).json()

    results = []

    for c in data:

        try:

            symbol = c["symbol"]

            if not symbol.endswith("USDT"):
                continue

            if not valid_symbol(symbol):
                continue

            pump = float(c["priceChangePercent"])

            volume = float(c["quoteVolume"])

            if (
                pump >= MIN_24H_PUMP
                and volume >= MIN_VOLUME
            ):

                results.append({
                    "exchange": "BINANCE",
                    "symbol": symbol,
                    "pump": pump
                })

        except:
            pass

    return results

# =========================================================
# KUCOIN
# =========================================================

def get_kucoin():

    url = "https://api.kucoin.com/api/v1/market/allTickers"

    data = requests.get(url, timeout=20).json()["data"]["ticker"]

    results = []

    for c in data:

        try:

            symbol = c["symbol"].replace("-", "")

            if not symbol.endswith("USDT"):
                continue

            if not valid_symbol(symbol):
                continue

            pump = float(c["changeRate"]) * 100

            volume = float(c["volValue"])

            if (
                pump >= MIN_24H_PUMP
                and volume >= MIN_VOLUME
            ):

                results.append({
                    "exchange": "KUCOIN",
                    "symbol": symbol,
                    "pump": pump
                })

        except:
            pass

    return results

# =========================================================
# BYBIT
# =========================================================

def get_bybit():

    url = "https://api.bybit.com/v5/market/tickers?category=spot"

    data = requests.get(url, timeout=20).json()["result"]["list"]

    results = []

    for c in data:

        try:

            symbol = c["symbol"]

            if not symbol.endswith("USDT"):
                continue

            if not valid_symbol(symbol):
                continue

            pump = float(c["price24hPcnt"]) * 100

            volume = float(c["turnover24h"])

            if (
                pump >= MIN_24H_PUMP
                and volume >= MIN_VOLUME
            ):

                results.append({
                    "exchange": "BYBIT",
                    "symbol": symbol,
                    "pump": pump
                })

        except:
            pass

    return results

# =========================================================
# GATEIO
# =========================================================

def get_gateio():

    url = "https://api.gateio.ws/api/v4/spot/tickers"

    data = requests.get(url, timeout=20).json()

    results = []

    for c in data:

        try:

            symbol = c["currency_pair"].replace("_", "")

            if not symbol.endswith("USDT"):
                continue

            if not valid_symbol(symbol):
                continue

            pump = float(c["change_percentage"])

            volume = float(c["quote_volume"])

            if (
                pump >= MIN_24H_PUMP
                and volume >= MIN_VOLUME
            ):

                results.append({
                    "exchange": "GATEIO",
                    "symbol": symbol,
                    "pump": pump
                })

        except:
            pass

    return results

# =========================================================
# PATTERNS
# =========================================================

def upper_wick(df):

    candle = df.iloc[-1]

    body = abs(
        candle["close"] - candle["open"]
    )

    wick = candle["high"] - max(
        candle["open"],
        candle["close"]
    )

    if body == 0:
        body = 0.0001

    return (wick / body) >= 2

def weak_volume(df):

    recent = df["volume"].tail(3).mean()

    old = df["volume"].tail(15).head(12).mean()

    return recent < old

def bearish_engulfing(df):

    prev = df.iloc[-2]

    curr = df.iloc[-1]

    return (
        prev["close"] > prev["open"]
        and
        curr["close"] < curr["open"]
        and
        curr["open"] > prev["close"]
        and
        curr["close"] < prev["open"]
    )

# =========================================================
# ANALYZE
# =========================================================

def analyze(exchange, symbol):

    try:

        if exchange == "BINANCE":

            df5 = get_binance_klines(symbol, "5m")
            df15 = get_binance_klines(symbol, "15m")
            df1h = get_binance_klines(symbol, "1h")

        elif exchange == "KUCOIN":

            df5 = get_kucoin_klines(symbol, "5min")
            df15 = get_kucoin_klines(symbol, "15min")
            df1h = get_kucoin_klines(symbol, "1hour")

        elif exchange == "BYBIT":

            df5 = get_bybit_klines(symbol, "5")
            df15 = get_bybit_klines(symbol, "15")
            df1h = get_bybit_klines(symbol, "60")

        else:

            df5 = get_gateio_klines(symbol, "5m")
            df15 = get_gateio_klines(symbol, "15m")
            df1h = get_gateio_klines(symbol, "1h")

        price = float(df5["close"].iloc[-1])

        # RSI
        df5["RSI"] = calculate_rsi(df5["close"])
        df15["RSI"] = calculate_rsi(df15["close"])
        df1h["RSI"] = calculate_rsi(df1h["close"])

        rsi5 = float(df5["RSI"].iloc[-1])
        rsi15 = float(df15["RSI"].iloc[-1])
        rsi1h = float(df1h["RSI"].iloc[-1])

        # EMA
        df5["EMA20"] = ema(df5["close"])

        ema20 = float(df5["EMA20"].iloc[-1])

        stretch = (
            (price - ema20)
            / ema20
        ) * 100

        # ATR
        df5["ATR"] = atr(df5)

        atr_value = float(df5["ATR"].iloc[-1])

        wick = upper_wick(df5)

        volume_weak = weak_volume(df5)

        bearish = bearish_engulfing(df5)

        # AI SCORE
        score = 0

        if rsi5 > 80:
            score += 20

        if rsi15 > 75:
            score += 15

        if rsi1h > 70:
            score += 10

        if stretch > 10:
            score += 15

        if wick:
            score += 15

        if bearish:
            score += 10

        if volume_weak:
            score += 15

        # ENTRY ZONE
        entry_low = round(price * 1.01, 8)

        entry_high = round(price * 1.03, 8)

        # EXPECTED DROP
        expected_drop = round(stretch * 0.8, 2)

        return {

            "score": score,

            "price": price,

            "rsi5": rsi5,
            "rsi15": rsi15,
            "rsi1h": rsi1h,

            "wick": wick,

            "bearish": bearish,

            "volume_weak": volume_weak,

            "stretch": stretch,

            "entry_low": entry_low,
            "entry_high": entry_high,

            "expected_drop": expected_drop,

            "atr": atr_value
        }

    except Exception as e:

        print(exchange, symbol, e)

        return None

# =========================================================
# MAIN
# =========================================================

already_sent = set()

print("🚀 AI MULTI EXCHANGE SCANNER STARTED")

send_telegram(
    "🚀 AI MULTI EXCHANGE REVERSAL SCANNER STARTED"
)

while True:

    try:

        coins = (
            get_binance()
            + get_kucoin()
            + get_bybit()
            + get_gateio()
        )

        print("CANDIDATES:", len(coins))

        for coin in coins:

            exchange = coin["exchange"]

            symbol = coin["symbol"]

            uid = f"{exchange}_{symbol}"

            if uid in already_sent:
                continue

            result = analyze(exchange, symbol)

            if not result:
                continue

            score = result["score"]

            if score < 70:
                continue

            color = {
                "BINANCE": "🟡",
                "KUCOIN": "🟣",
                "BYBIT": "🔵",
                "GATEIO": "🟢"
            }.get(exchange, "⚪")

            probability = "MEDIUM"

            if score >= 90:
                probability = "EXTREME"

            elif score >= 80:
                probability = "HIGH"

            message = f"""
{color} <b>{exchange}</b>

🔥 ELITE SHORT SIGNAL

💰 <b>{symbol}</b>

🧠 AI SCORE:
<b>{score}/100</b>

━━━━━━━━━━━━━━

📈 24H Pump:
<b>{coin['pump']:.2f}%</b>

━━━━━━━━━━━━━━

📊 RSI 5M:
<b>{result['rsi5']:.2f}</b>

📊 RSI 15M:
<b>{result['rsi15']:.2f}</b>

📊 RSI 1H:
<b>{result['rsi1h']:.2f}</b>

━━━━━━━━━━━━━━

🕯 Upper Wick:
<b>{result['wick']}</b>

📉 Weak Volume:
<b>{result['volume_weak']}</b>

🔻 Bearish Pattern:
<b>{result['bearish']}</b>

📏 EMA Stretch:
<b>{result['stretch']:.2f}%</b>

━━━━━━━━━━━━━━

🎯 SHORT ENTRY:
<b>{result['entry_low']}</b>
→
<b>{result['entry_high']}</b>

📉 Expected Drop:
<b>-{result['expected_drop']}%</b>

⚠️ Reversal Probability:
<b>{probability}</b>

━━━━━━━━━━━━━━

💵 Position:
<b>5$</b>

⚡ Leverage:
<b>2x Isolated</b>

🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

            print(message)

            send_telegram(message)

            already_sent.add(uid)

    except Exception as e:

        print("MAIN ERROR:", e)

    time.sleep(CHECK_INTERVAL)
