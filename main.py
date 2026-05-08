# =========================================================
# PROFESSIONAL AI BINANCE SCANNER
# MAIN.PY
# =========================================================

import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# =========================================================
# CONFIG
# =========================================================

TELEGRAM_TOKEN = "8628541851:AAGTo4LDtxv8WOy40L5YI7kqIdwv2SLNUKI"

CHAT_IDS = ["5067771509",
    "-1003890327415"
]

INTERVAL = 180

MAX_COINS_TO_SCAN = 200

# SHORT
MIN_PUMP = 8
MIN_SCORE_SHORT = 70

# LONG
MIN_SCORE_LONG = 24

# FILTERS
MIN_VOLUME_USDT = 1000000

MIN_ATR_PERCENT = 1.5
MAX_ATR_PERCENT = 5.0

REQUIRE_GOLDEN_CROSS = True

# PORTFOLIO
ACCOUNT_BALANCE = 1000
RISK_PER_TRADE = 0.01
MAX_LEVERAGE = 2

# COOLDOWN
SIGNAL_COOLDOWN_HOURS = 2

# =========================================================
# MEMORY
# =========================================================

sent_short = {}
sent_long = {}

# =========================================================
# TELEGRAM
# =========================================================

def send(msg):

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    for chat in CHAT_IDS:

        try:

            requests.post(
                url,
                data={
                    "chat_id": chat,
                    "text": msg,
                    "parse_mode": "HTML"
                },
                timeout=10
            )

        except Exception as e:
            print(e)

# =========================================================
# INDICATORS
# =========================================================

def ema(series, period):

    return series.ewm(
        span=period,
        adjust=False
    ).mean()

# =========================================================

def rsi(series, period=14):

    delta = series.diff()

    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    avg_gain = gain.ewm(
        alpha=1/period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1/period,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))

# =========================================================

def macd(series):

    ema12 = ema(series, 12)
    ema26 = ema(series, 26)

    macd_line = ema12 - ema26

    signal_line = ema(
        macd_line,
        9
    )

    hist = macd_line - signal_line

    return macd_line, signal_line, hist

# =========================================================

def calculate_bollinger_bands(df, period=20, std=2):

    middle = df['c'].rolling(period).mean()

    std_dev = df['c'].rolling(period).std()

    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)

    return upper, middle, lower

# =========================================================

def calculate_atr(df, period=14):

    high = df['h']
    low = df['l']
    close = df['c']

    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())

    tr = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)

    atr = tr.ewm(
        span=period,
        adjust=False
    ).mean()

    current_price = close.iloc[-1]

    atr_percent = (
        atr.iloc[-1] / current_price
    ) * 100

    return {
        'atr': atr.iloc[-1],
        'atr_percent': atr_percent,
        'is_good': (
            MIN_ATR_PERCENT <= atr_percent <= MAX_ATR_PERCENT
        )
    }

# =========================================================

def adx(df, period=14):

    high = df['h']
    low = df['l']
    close = df['c']

    plus_dm = high.diff()
    minus_dm = low.diff() * -1

    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0

    tr = pd.concat([
        high - low,
        abs(high - close.shift()),
        abs(low - close.shift())
    ], axis=1).max(axis=1)

    atr_val = tr.rolling(period).mean()

    plus_di = 100 * (
        plus_dm.rolling(period).mean() / atr_val
    )

    minus_di = 100 * (
        minus_dm.rolling(period).mean() / atr_val
    )

    dx = abs(
        plus_di - minus_di
    ) / (
        plus_di + minus_di
    ) * 100

    return dx.rolling(period).mean()

# =========================================================
# PATTERNS
# =========================================================

def check_golden_cross(df):

    df['ema_50'] = ema(df['c'], 50)
    df['ema_200'] = ema(df['c'], 200)

    ema_50_current = df['ema_50'].iloc[-1]
    ema_200_current = df['ema_200'].iloc[-1]

    ema_50_prev = df['ema_50'].iloc[-2]
    ema_200_prev = df['ema_200'].iloc[-2]

    if ema_50_prev <= ema_200_prev and ema_50_current > ema_200_current:

        return True, "Golden Cross detected ✅"

    elif ema_50_current > ema_200_current:

        return True, "EMA 50 above EMA 200 🟢"

    return False, "No golden cross"

# =========================================================

def check_bullish_candles(df):

    last = df.iloc[-1]
    prev = df.iloc[-2]

    bullish = (
        last['c'] > last['o']
    )

    engulfing = (
        last['c'] > last['o']
        and last['o'] < prev['c']
        and last['c'] > prev['o']
    )

    if engulfing:
        return "Bullish Engulfing 🟢", True

    if bullish:
        return "Bullish Candle 📈", False

    return "Neutral ⚪", False

# =========================================================

def wick(df):

    c = df.iloc[-1]

    body = abs(c["c"] - c["o"])

    upper = c["h"] - max(
        c["c"],
        c["o"]
    )

    if body == 0:
        body = 0.001

    return upper / body > 2

# =========================================================

def volume_weak(df):

    return (
        df["v"].tail(3).mean()
        <
        df["v"].tail(15).mean()
    )

# =========================================================

def bearish(df):

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    return (

        prev["c"] > prev["o"]

        and

        curr["c"] < curr["o"]

        and

        curr["o"] > prev["c"]

    )

# =========================================================
# RISK
# =========================================================

def calculate_position_size(
    balance,
    risk_percent,
    entry,
    stop
):

    risk_amount = balance * risk_percent

    stop_distance = abs(entry - stop)

    if stop_distance == 0:
        return 0

    size = risk_amount / stop_distance

    return round(size, 2)

# =========================================================
# BINANCE DATA
# =========================================================

def klines(symbol, interval='15m', limit=250):

    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={symbol}"
        f"&interval={interval}"
        f"&limit={limit}"
    )

    try:

        data = requests.get(
            url,
            timeout=10
        ).json()

        if 'code' in data:
            return None

        df = pd.DataFrame(data)

        df = df.iloc[:, :6]

        df.columns = [
            "t",
            "o",
            "h",
            "l",
            "c",
            "v"
        ]

        for col in [
            "o",
            "h",
            "l",
            "c",
            "v"
        ]:
            df[col] = pd.to_numeric(df[col])

        return df

    except:
        return None

# =========================================================

def klines_multiple_timeframes(symbol):

    dataframes = {}

    for tf in ['15m', '1h', '4h']:

        df = klines(
            symbol,
            tf,
            250
        )

        if df is not None and len(df) >= 200:
            dataframes[tf] = df

    return dataframes

# =========================================================

def get_all_usdt_pairs(limit=200):

    try:

        info = requests.get(
            "https://api.binance.com/api/v3/exchangeInfo"
        ).json()

        tickers = requests.get(
            "https://api.binance.com/api/v3/ticker/24hr"
        ).json()

        symbols = []

        for s in info['symbols']:

            if (
                s['quoteAsset'] == 'USDT'
                and
                s['status'] == 'TRADING'
            ):
                symbols.append(s['symbol'])

        volume_map = {}

        for t in tickers:

            try:
                volume_map[t['symbol']] = float(
                    t['quoteVolume']
                )
            except:
                volume_map[t['symbol']] = 0

        symbols.sort(
            key=lambda x: volume_map.get(x, 0),
            reverse=True
        )

        return symbols[:limit]

    except:
        return []

# =========================================================
# MARKET FILTER
# =========================================================

def market_is_bullish():

    btc = klines(
        "BTCUSDT",
        '1h',
        250
    )

    if btc is None:
        return False

    ema50 = ema(
        btc['c'],
        50
    ).iloc[-1]

    ema200 = ema(
        btc['c'],
        200
    ).iloc[-1]

    return ema50 > ema200

# =========================================================
# LONG SCANNER
# =========================================================

def scan_long_opportunities(limit=200):

    symbols = get_all_usdt_pairs(limit)

    opportunities = []

    bullish_market = market_is_bullish()

    for sym in symbols:

        try:

            dataframes = klines_multiple_timeframes(sym)

            if not dataframes:
                continue

            total_score = 0

            analyses = {}

            for tf, df in dataframes.items():

                current_price = df['c'].iloc[-1]

                volume_usdt = (
                    current_price *
                    df['v'].iloc[-1]
                )

                if volume_usdt < MIN_VOLUME_USDT:
                    continue

                df['rsi'] = rsi(df['c'])

                current_rsi = df['rsi'].iloc[-1]

                upper, middle, lower = calculate_bollinger_bands(df)

                golden_cross, gc_message = check_golden_cross(df)

                candle_pattern, engulfing = check_bullish_candles(df)

                macd_line, signal_line, hist = macd(df['c'])

                atr_data = calculate_atr(df)

                if not atr_data['is_good']:
                    continue

                adx_value = adx(df).iloc[-1]

                tf_score = 0

                if current_rsi > 55:
                    tf_score += 4

                if hist.iloc[-1] > 0:
                    tf_score += 3

                if golden_cross:
                    tf_score += 7

                if engulfing:
                    tf_score += 4

                if current_price > middle.iloc[-1]:
                    tf_score += 3

                avg_vol = df['v'].tail(20).mean()

                if df['v'].iloc[-1] > avg_vol * 1.5:
                    tf_score += 4

                if adx_value > 20:
                    tf_score += 4

                weight = (
                    3 if tf == '4h'
                    else 2 if tf == '1h'
                    else 1
                )

                total_score += tf_score * weight

                analyses[tf] = {
                    'rsi': current_rsi,
                    'gc_message': gc_message,
                    'candle_pattern': candle_pattern,
                    'atr_percent': atr_data['atr_percent']
                }

            if total_score < MIN_SCORE_LONG:
                continue

            if REQUIRE_GOLDEN_CROSS:

                tf4h = analyses.get('4h')

                if not tf4h:
                    continue

            if not bullish_market:
                continue

            main_df = dataframes['15m']

            current_price = main_df['c'].iloc[-1]

            atr_value = calculate_atr(main_df)['atr']

            stop_loss = current_price - (atr_value * 1.5)

            tp1 = current_price + (atr_value * 2)

            tp2 = current_price + (atr_value * 4)

            rr = (
                (tp2 - current_price)
                /
                (current_price - stop_loss)
            )

            position_size = calculate_position_size(
                ACCOUNT_BALANCE,
                RISK_PER_TRADE,
                current_price,
                stop_loss
            )

            opportunities.append({

                'symbol': sym,
                'score': total_score,
                'current_price': current_price,
                'stop_loss': stop_loss,
                'tp1': tp1,
                'tp2': tp2,
                'rr': rr,
                'position_size': position_size,
                'analyses': analyses

            })

        except Exception as e:
            print(e)

    opportunities.sort(
        key=lambda x: x['score'],
        reverse=True
    )

    return opportunities

# =========================================================
# SHORT SCANNER
# =========================================================

def scan_short_opportunities():

    url = "https://api.binance.com/api/v3/ticker/24hr"

    try:
        data = requests.get(url).json()
    except:
        return []

    opportunities = []

    for c in data:

        try:

            sym = c['symbol']

            if not sym.endswith("USDT"):
                continue

            pump = float(
                c['priceChangePercent']
            )

            volume = float(
                c['quoteVolume']
            )

            if volume < MIN_VOLUME_USDT:
                continue

            if pump < MIN_PUMP:
                continue

            df = klines(
                sym,
                '5m',
                120
            )

            if df is None:
                continue

            df['rsi'] = rsi(df['c'])

            current_rsi = df['rsi'].iloc[-1]

            ema20 = ema(
                df['c'],
                20
            ).iloc[-1]

            current_price = df['c'].iloc[-1]

            stretch = (
                (
                    current_price - ema20
                ) / ema20
            ) * 100

            macd_line, signal_line, hist = macd(df['c'])

            atr_data = calculate_atr(df)

            if not atr_data['is_good']:
                continue

            score = 0

            if current_rsi > 70:
                score += 15

            if current_rsi > 80:
                score += 10

            if stretch > 5:
                score += 10

            if wick(df):
                score += 15

            if volume_weak(df):
                score += 10

            if bearish(df):
                score += 15

            if hist.iloc[-1] < 0:
                score += 10

            if score < MIN_SCORE_SHORT:
                continue

            entry_low = current_price * 1.01
            entry_high = current_price * 1.03

            expected_drop = abs(stretch * 0.7)

            stop_loss = current_price * 1.03

            position_size = calculate_position_size(
                ACCOUNT_BALANCE,
                RISK_PER_TRADE,
                current_price,
                stop_loss
            )

            opportunities.append({

                'symbol': sym,
                'score': score,
                'current_price': current_price,
                'entry_low': entry_low,
                'entry_high': entry_high,
                'drop': expected_drop,
                'position_size': position_size,
                'atr_percent': atr_data['atr_percent']

            })

        except:
            continue

    opportunities.sort(
        key=lambda x: x['score'],
        reverse=True
    )

    return opportunities

# =========================================================
# MESSAGE FORMAT
# =========================================================

def format_long_message(opp):

    return f"""
🚀🚀🚀 <b>BULLISH OPPORTUNITY</b> 🚀🚀🚀

━━━━━━━━━━━━━━━━━━
<b>PAIR:</b> {opp['symbol']}
<b>AI SCORE:</b> {opp['score']} / 100
━━━━━━━━━━━━━━━━━━

<b>💰 CURRENT PRICE:</b>
${opp['current_price']:.6f}

━━━━━━━━━━━━━━━━━━
<b>📊 TECHNICAL ANALYSIS</b>
━━━━━━━━━━━━━━━━━━

📈 Multi Timeframe Bullish
📊 MACD Momentum Positive
📊 RSI Momentum Confirmed
🟡 Golden Cross Confirmed
📊 ATR Volatility Healthy

━━━━━━━━━━━━━━━━━━
<b>💡 TRADE SETUP (LONG)</b>
━━━━━━━━━━━━━━━━━━

🎯 TP1:
{opp['tp1']:.6f}

🎯 TP2:
{opp['tp2']:.6f}

🛑 STOP LOSS:
{opp['stop_loss']:.6f}

⚖️ R/R:
{opp['rr']:.2f}

━━━━━━━━━━━━━━━━━━
<b>💼 RISK MANAGEMENT</b>
━━━━━━━━━━━━━━━━━━

💰 POSITION SIZE:
{opp['position_size']} USDT

⚡ LEVERAGE:
x{MAX_LEVERAGE}

━━━━━━━━━━━━━━━━━━
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
━━━━━━━━━━━━━━━━━━
"""

# =========================================================

def format_short_message(opp):

    return f"""
🔥 BINANCE SHORT OPPORTUNITY

━━━━━━━━━━━━━━━━━━

💰 PAIR:
{opp['symbol']}

🧠 AI SCORE:
{opp['score']} / 100

━━━━━━━━━━━━━━━━━━

📉 EXPECTED DROP:
{opp['drop']:.2f}%

📊 ATR:
{opp['atr_percent']:.2f}%

━━━━━━━━━━━━━━━━━━

🔴 ENTRY ZONE:
{opp['entry_low']:.6f}
→
{opp['entry_high']:.6f}

━━━━━━━━━━━━━━━━━━

💰 POSITION SIZE:
{opp['position_size']} USDT

⚡ LEVERAGE:
x{MAX_LEVERAGE}

━━━━━━━━━━━━━━━━━━
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
━━━━━━━━━━━━━━━━━━
"""

# =========================================================
# START
# =========================================================

print("🚀 PROFESSIONAL AI SCANNER STARTED")

send(
    "🚀 <b>PROFESSIONAL AI SCANNER STARTED</b>\n\n"
    "📈 Advanced LONG + SHORT Scanner\n"
    "📊 ATR + RSI + MACD + ADX\n"
    "🟡 Golden Cross Filter\n"
    "💼 Portfolio Protection Enabled"
)

# =========================================================
# MAIN LOOP
# =========================================================

while True:

    try:

        print("\n━━━━━━━━━━━━━━━━━━")
        print(datetime.now())
        print("Starting scan...")
        print("━━━━━━━━━━━━━━━━━━")

        # =================================================
        # SHORT
        # =================================================

        short_opps = scan_short_opportunities()

        for opp in short_opps[:5]:

            last_sent = sent_short.get(
                opp['symbol']
            )

            if last_sent:

                if (
                    datetime.now() - last_sent
                    <
                    timedelta(hours=SIGNAL_COOLDOWN_HOURS)
                ):
                    continue

            send(
                format_short_message(opp)
            )

            sent_short[opp['symbol']] = datetime.now()

            print(
                f"SHORT: {opp['symbol']} | Score {opp['score']}"
            )

        # =================================================
        # LONG
        # =================================================

        long_opps = scan_long_opportunities(
            MAX_COINS_TO_SCAN
        )

        for opp in long_opps[:5]:

            last_sent = sent_long.get(
                opp['symbol']
            )

            if last_sent:

                if (
                    datetime.now() - last_sent
                    <
                    timedelta(hours=SIGNAL_COOLDOWN_HOURS)
                ):
                    continue

            send(
                format_long_message(opp)
            )

            sent_long[opp['symbol']] = datetime.now()

            print(
                f"LONG: {opp['symbol']} | Score {opp['score']}"
            )

        print(
            f"Waiting {INTERVAL} seconds..."
        )

        time.sleep(INTERVAL)

    except Exception as e:

        print(f"ERROR: {e}")

        time.sleep(60)
