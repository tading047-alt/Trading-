import time
import requests
import pandas as pd
from datetime import datetime

# =====================================================
# CONFIG
# =====================================================

TELEGRAM_BOT_TOKEN = "8628541851:AAGTo4LDtxv8WOy40L5YI7kqIdwv2SLNUKI"
TELEGRAM_CHAT_ID = "5067771509"

CHECK_INTERVAL = 180

MIN_24H_PUMP = 50
MIN_RSI = 80
MIN_VOLUME_USDT = 500000

# =====================================================
# TELEGRAM
# =====================================================

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

# =====================================================
# RSI
# =====================================================

def calculate_rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)

    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()

    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss

    rsi = 100 - (100 / (1 + rs))

    return rsi

# =====================================================
# GET KLINES BINANCE
# =====================================================

def get_binance_klines(symbol, interval="5m", limit=100):

    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={symbol}&interval={interval}&limit={limit}"
    )

    response = requests.get(url, timeout=20)

    data = response.json()

    df = pd.DataFrame(data)

    df = df.iloc[:, :6]

    df.columns = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume"
    ]

    cols = ["open", "high", "low", "close", "volume"]

    for col in cols:
        df[col] = pd.to_numeric(df[col])

    return df

# =====================================================
# GET KLINES GATEIO
# =====================================================

def get_gateio_klines(symbol, interval="5m", limit=100):

    gate_interval = {
        "5m": "5m",
        "15m": "15m",
        "1h": "1h",
        "4h": "4h",
        "1d": "1d"
    }

    pair = symbol.replace("USDT", "_USDT")

    url = (
        f"https://api.gateio.ws/api/v4/spot/candlesticks"
        f"?currency_pair={pair}"
        f"&interval={gate_interval[interval]}"
        f"&limit={limit}"
    )

    response = requests.get(url, timeout=20)

    data = response.json()

    rows = []

    for row in data:

        rows.append({
            "open": float(row[5]),
            "high": float(row[3]),
            "low": float(row[4]),
            "close": float(row[2]),
            "volume": float(row[1])
        })

    df = pd.DataFrame(rows)

    return df

# =====================================================
# CHANGE
# =====================================================

def calculate_change(df):

    first = df["close"].iloc[0]

    last = df["close"].iloc[-1]

    if first == 0:
        return 0

    return ((last - first) / first) * 100

# =====================================================
# UPPER WICK
# =====================================================

def has_long_upper_wick(df):

    candle = df.iloc[-1]

    body = abs(
        candle["close"] - candle["open"]
    )

    upper_wick = candle["high"] - max(
        candle["open"],
        candle["close"]
    )

    if body == 0:
        body = 0.0001

    return (upper_wick / body) >= 2

# =====================================================
# WEAK VOLUME
# =====================================================

def weak_volume(df):

    recent = df["volume"].tail(3).mean()

    previous = df["volume"].tail(10).head(7).mean()

    return recent < previous

# =====================================================
# FILTER LEVERAGED TOKENS
# =====================================================

def is_valid_symbol(symbol):

    blocked_words = [
        "3L",
        "3S",
        "5L",
        "5S",
        "BULL",
        "BEAR"
    ]

    if any(word in symbol for word in blocked_words):
        return False

    return True

# =====================================================
# GET BINANCE CANDIDATES
# =====================================================

def get_binance_candidates():

    url = "https://api.binance.com/api/v3/ticker/24hr"

    response = requests.get(url, timeout=20)

    data = response.json()

    results = []

    for coin in data:

        try:

            symbol = coin["symbol"]

            if not symbol.endswith("USDT"):
                continue

            if not is_valid_symbol(symbol):
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
                    "exchange": "BINANCE",
                    "symbol": symbol,
                    "change_24h": change_24h
                })

        except:
            pass

    return results

# =====================================================
# GET GATEIO CANDIDATES
# =====================================================

def get_gateio_candidates():

    url = "https://api.gateio.ws/api/v4/spot/tickers"

    response = requests.get(url, timeout=20)

    data = response.json()

    results = []

    for coin in data:

        try:

            symbol = coin["currency_pair"]

            if not symbol.endswith("_USDT"):
                continue

            clean_symbol = symbol.replace("_", "")

            if not is_valid_symbol(clean_symbol):
                continue

            change_24h = float(
                coin["change_percentage"]
            )

            volume = float(
                coin["quote_volume"]
            )

            if (
                change_24h >= MIN_24H_PUMP
                and volume >= MIN_VOLUME_USDT
            ):

                results.append({
                    "exchange": "GATEIO",
                    "symbol": clean_symbol,
                    "change_24h": change_24h
                })

        except:
            pass

    return results

# =====================================================
# ANALYZE
# =====================================================

def analyze(symbol, exchange):

    try:

        if exchange == "BINANCE":
            get_klines = get_binance_klines
            color = "🟡"

        else:
            get_klines = get_gateio_klines
            color = "🟢"

        df_5m = get_klines(symbol, "5m", 100)

        df_15m = get_klines(symbol, "15m", 100)

        df_1h = get_klines(symbol, "1h", 100)

        df_4h = get_klines(symbol, "4h", 100)

        df_1d = get_klines(symbol, "1d", 4)

        df_5m["RSI"] = calculate_rsi(
            df_5m["close"]
        )

        rsi = float(
            df_5m["RSI"].iloc[-1]
        )

        wick = (
            has_long_upper_wick(df_5m)
            or
            has_long_upper_wick(df_15m)
        )

        volume_weak = weak_volume(df_5m)

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
            and volume_weak
        )

        return {
            "signal": signal,
            "rsi": rsi,
            "wick": wick,
            "weak_volume": volume_weak,
            "change_1h": change_1h,
            "change_4h": change_4h,
            "change_3d": change_3d,
            "color": color
        }

    except Exception as e:

        print("Analyze Error:", symbol, e)

        return None

# =====================================================
# MAIN
# =====================================================

already_sent = set()

print("MULTI EXCHANGE BOT STARTED")

send_telegram(
    "🚀 MULTI EXCHANGE SCALPING BOT STARTED"
)

while True:

    try:

        all_candidates = (
            get_binance_candidates()
            +
            get_gateio_candidates()
        )

        print("Candidates:", len(all_candidates))

        for coin in all_candidates:

            exchange = coin["exchange"]

            symbol = coin["symbol"]

            unique_id = f"{exchange}_{symbol}"

            if unique_id in already_sent:
                continue

            result = analyze(symbol, exchange)

            if not result:
                continue

            if result["signal"]:

                message = f"""
{result['color']} <b>{exchange}</b>

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

📊 RSI:
<b>{result['rsi']:.2f}</b>

🕯 Long Upper Wick:
<b>{result['wick']}</b>

📉 Weak Volume:
<b>{result['weak_volume']}</b>

━━━━━━━━━━━━━━

💵 Entry: <b>5$</b>
⚡ Leverage: <b>2x</b>

🎯 Target:
<b>1$ Profit</b>

🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

                print(message)

                send_telegram(message)

                already_sent.add(unique_id)

    except Exception as e:

        print("MAIN ERROR:", e)

    time.sleep(CHECK_INTERVAL)
