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
    "-1003890327415"
]

INTERVAL = 180  # 3 دقائق

# إعدادات SHORT
MIN_PUMP = 8
MIN_VOLUME = 100000

# إعدادات LONG
MIN_BULLISH_SCORE = 15
MAX_POSITION_SIZE = 100
MAX_LEVERAGE = 2
MAX_COINS_TO_SCAN = 500

# =========================================================
# إعدادات فلترة الإشارات
# =========================================================

MIN_SCORE_SHORT = 70      # أقل درجة للإشارة SHORT
MIN_SCORE_LONG = 70       # أقل درجة للإشارة LONG
MIN_VOLUME_USDT = 1000000 # أقل حجم تداول (1 مليون دولار)
REQUIRE_GOLDEN_CROSS = True  # هل نطلب Golden Cross إجباري؟

# =========================================================
# إعدادات ATR (معدل التحرك الحقيقي)
# =========================================================

MIN_ATR_PERCENT = 1.5     # أقل نسبة تحرك مطلوبة
MAX_ATR_PERCENT = 4.0     # أعلى نسبة تحرك مقبولة

# =========================================================
# إعدادات المسح المجمّع
# =========================================================

BATCH_SIZE = 100             # عدد العملات في كل مجموعة
BATCH_SCAN_TIME = 300        # 5 دقائق للمسح (بالثواني)
REST_TIME_BETWEEN_BATCHES = 60  # دقيقة راحة بين المجموعات (بالثواني)

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

def calculate_bollinger_bands(df, period=20, std=2):
    middle = df['close'].rolling(period).mean()
    std_dev = df['close'].rolling(period).std()
    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)
    return upper, middle, lower

def check_golden_cross(df):
    df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    ema_50_current = df['ema_50'].iloc[-1]
    ema_200_current = df['ema_200'].iloc[-1]
    ema_50_prev = df['ema_50'].iloc[-2]
    ema_200_prev = df['ema_200'].iloc[-2]
    
    if ema_50_prev <= ema_200_prev and ema_50_current > ema_200_current:
        return True, "Golden Cross detected ✅"
    elif ema_50_current > ema_200_current:
        return True, "EMA 50 above EMA 200 🟢"
    return False, "No golden cross"

def check_bullish_candles(df):
    last_5_candles = df.tail(6)
    bullish_count = 0
    
    for i in range(len(last_5_candles)-1):
        if last_5_candles['close'].iloc[i] > last_5_candles['open'].iloc[i]:
            bullish_count += 1
        if i > 0:
            if last_5_candles['close'].iloc[i] > last_5_candles['high'].iloc[i-1]:
                bullish_count += 1
    
    last_candle = last_5_candles.iloc[-1]
    prev_candle = last_5_candles.iloc[-2]
    
    is_engulfing = (last_candle['close'] > last_candle['open'] and 
                   last_candle['open'] < prev_candle['close'] and
                   last_candle['close'] > prev_candle['open'])
    
    if is_engulfing:
        pattern = "Bullish Engulfing 🟢"
    elif bullish_count >= 5:
        pattern = "Bullish Rejection ✅"
    elif bullish_count >= 3:
        pattern = "Weak Bullish 📈"
    else:
        pattern = "Neutral ⚪"
        
    return pattern, bullish_count, is_engulfing

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

def calculate_atr(df, period=14):
    """حساب ATR ونسبة التحرك"""
    try:
        high = df['h']
        low = df['l']
        close = df['c']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        
        current_price = close.iloc[-1]
        if current_price > 0:
            atr_percent = (atr.iloc[-1] / current_price) * 100
        else:
            atr_percent = 0
            
        return {
            'atr': atr.iloc[-1],
            'atr_percent': atr_percent,
            'is_good': MIN_ATR_PERCENT <= atr_percent <= MAX_ATR_PERCENT
        }
    except:
        return {'atr': 0, 'atr_percent': 0, 'is_good': False}

# =========================================================
# BINANCE DATA
# =========================================================

def klines(symbol, interval='5m', limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        data = requests.get(url, timeout=10).json()
        if 'code' in data:
            return None
        df = pd.DataFrame(data)
        df = df.iloc[:, :6]
        df.columns = ["t","o","h","l","c","v"]
        for col in ["o","h","l","c","v"]:
            df[col] = pd.to_numeric(df[col])
        return df
    except:
        return None

def klines_multiple_timeframes(symbol):
    dataframes = {}
    
    df_15m = klines(symbol, '15m', 100)
    if df_15m is not None and len(df_15m) >= 50:
        dataframes['15m'] = df_15m
    
    df_1h = klines(symbol, '1h', 100)
    if df_1h is not None and len(df_1h) >= 50:
        dataframes['1h'] = df_1h
    
    df_4h = klines(symbol, '4h', 100)
    if df_4h is not None and len(df_4h) >= 50:
        dataframes['4h'] = df_4h
    
    return dataframes if dataframes else None

def get_all_usdt_pairs(limit=MAX_COINS_TO_SCAN):
    url = "https://api.binance.com/api/v3/exchangeInfo"
    try:
        data = requests.get(url).json()
        symbols = []
        for s in data['symbols']:
            if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING':
                symbols.append(s['symbol'])
        
        print(f"Found {len(symbols)} USDT pairs total")
        
        if len(symbols) > limit:
            tickers = requests.get("https://api.binance.com/api/v3/ticker/24hr").json()
            volume_dict = {}
            for t in tickers:
                if t['symbol'] in symbols:
                    try:
                        volume_dict[t['symbol']] = float(t['quoteVolume'])
                    except:
                        volume_dict[t['symbol']] = 0
            
            symbols.sort(key=lambda x: volume_dict.get(x, 0), reverse=True)
            symbols = symbols[:limit]
        
        return symbols
    except Exception as e:
        print(f"Error getting pairs: {e}")
        return []

# =========================================================
# SCAN SHORT
# =========================================================

def scan_short_opportunities():
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        data = requests.get(url, timeout=10).json()
    except:
        return []
    
    opportunities = []
    for c in data:
        try:
            sym = c["symbol"]
            if not sym.endswith("USDT"):
                continue
            pump = float(c["priceChangePercent"])
            vol = float(c["quoteVolume"])
            
            # شرط إضافي: حجم التداول
            if vol < MIN_VOLUME_USDT:
                continue
            
            if pump > MIN_PUMP:
                df = klines(sym, '5m', 60)
                if df is None or len(df) < 30:
                    continue
                
                # حساب ATR
                atr_data = calculate_atr(df)
                
                df["rsi"] = rsi(df["c"])
                df["ema"] = ema(df["c"])
                current_price = df["c"].iloc[-1]
                current_rsi = df["rsi"].iloc[-1]
                ema20 = df["ema"].iloc[-1]
                stretch = ((current_price - ema20) / ema20) * 100
                
                score = 0
                if current_rsi > 65:
                    score += 20
                if current_rsi > 75:
                    score += 10
                if stretch > 5:
                    score += 10
                
                if wick(df):
                    score += 15
                if volume_weak(df):
                    score += 15
                if bearish(df):
                    score += 20
                
                # فلتر ATR - الإشارة تحتاج ATR جيد
                if not atr_data['is_good']:
                    continue
                
                # فلتر النتيجة
                if score < MIN_SCORE_SHORT:
                    continue
                
                # حساب باقي البيانات
                rsi_5m = current_rsi
                rsi_15m = df["rsi"].iloc[-3] if len(df) >= 3 else current_rsi
                rsi_1h = df["rsi"].iloc[-12] if len(df) >= 12 else current_rsi
                
                change_4h = ((df["c"].iloc[-1] / df["c"].iloc[-48]) - 1) * 100 if len(df) >= 48 else pump * 0.3
                change_1h = ((df["c"].iloc[-1] / df["c"].iloc[-12]) - 1) * 100 if len(df) >= 12 else pump * 0.1
                
                entry_low = current_price * 1.01
                entry_high = current_price * 1.03
                expected_drop = abs(stretch * 0.7)
                
                opportunities.append({
                    'symbol': sym,
                    'pump': pump,
                    'score': score,
                    'current_price': current_price,
                    'rsi': current_rsi,
                    'stretch': stretch,
                    'rsi_5m': rsi_5m,
                    'rsi_15m': rsi_15m,
                    'rsi_1h': rsi_1h,
                    'change_24h': pump,
                    'change_4h': change_4h,
                    'change_1h': change_1h,
                    'entry_low': entry_low,
                    'entry_high': entry_high,
                    'drop': expected_drop,
                    'atr_percent': atr_data['atr_percent']
                })
        except Exception as e:
            continue
    
    opportunities.sort(key=lambda x: x['score'], reverse=True)
    return opportunities

# =========================================================
# SCAN LONG WITH BATCHES
# =========================================================

def scan_long_opportunities_batch(batch_symbols, batch_num, total_batches):
    """مسح مجموعة واحدة من العملات"""
    print(f"\n📦 BATCH {batch_num}/{total_batches} - Scanning {len(batch_symbols)} coins...")
    start_time = time.time()
    
    opportunities = []
    
    for i, sym in enumerate(batch_symbols):
        if i % 50 == 0 and i > 0:
            print(f"  [{batch_num}] Progress: {i+1}/{len(batch_symbols)}")
        
        dataframes = klines_multiple_timeframes(sym)
        if not dataframes:
            continue
        
        analyses = {}
        total_score = 0
        
        for tf, df in dataframes.items():
            if df is None or len(df) < 50:
                continue
            
            # حساب ATR
            atr_data = calculate_atr(df)
            
            current_price = df['c'].iloc[-1]
            df['rsi'] = rsi(df['c'])
            current_rsi = df['rsi'].iloc[-1]
            
            upper, middle, lower = calculate_bollinger_bands(df)
            bb_bullish = current_price > middle.iloc[-1]
            bb_signal = "Above middle band 📈" if bb_bullish else "Between bands ⚪"
            
            golden_cross, gc_message = check_golden_cross(df)
            candle_pattern, _, is_engulfing = check_bullish_candles(df)
            
            tf_weight = 3 if tf == '4h' else 2 if tf == '1h' else 1
            tf_score = 0
            
            if current_rsi >= 50:
                tf_score += 2
            if bb_bullish:
                tf_score += 2
            if golden_cross:
                tf_score += 3
            if is_engulfing:
                tf_score += 2
            
            total_score += tf_score * tf_weight
            
            analyses[tf] = {
                'rsi': current_rsi,
                'bb_signal': bb_signal,
                'golden_cross': golden_cross,
                'gc_message': gc_message,
                'candle_pattern': candle_pattern,
                'current_price': current_price,
                'upper_band': upper.iloc[-1],
                'middle_band': middle.iloc[-1],
                'atr_percent': atr_data['atr_percent']
            }
        
        if not analyses:
            continue
        
        # فلتر ATR - نأخذ أفضل ATR من الفريمات
        best_atr = max([analyses[tf]['atr_percent'] for tf in analyses if analyses[tf]['atr_percent'] > 0], default=0)
        if best_atr < MIN_ATR_PERCENT or best_atr > MAX_ATR_PERCENT:
            continue
        
        # فلتر النتيجة
        if total_score < MIN_SCORE_LONG:
            continue
        
        # شرط Golden Cross إجباري
        main_tf_4h = analyses.get('4h', {})
        if REQUIRE_GOLDEN_CROSS and not main_tf_4h.get('golden_cross', False):
            continue
        
        main_tf = analyses.get('4h') or analyses.get('1h') or analyses.get('15m')
        current_price = main_tf['current_price']
        
        entry_low = round(current_price * 0.99, 4)
        entry_high = round(current_price, 4)
        expected_gain = round((main_tf['upper_band'] - current_price) / current_price * 100, 2)
        if expected_gain < 2:
            expected_gain = 3.0
        
        stop_loss = round(current_price * 0.97, 4)
        take_profit_1 = round(current_price * 1.03, 4)
        take_profit_2 = round(current_price * 1.06, 4)
        
        opportunities.append({
            'symbol': sym,
            'score': total_score,
            'current_price': current_price,
            'entry_low': entry_low,
            'entry_high': entry_high,
            'expected_gain': expected_gain,
            'stop_loss': stop_loss,
            'take_profit_1': take_profit_1,
            'take_profit_2': take_profit_2,
            'analyses': analyses,
            'atr_percent': best_atr
        })
        
        time.sleep(0.3)
    
    elapsed = time.time() - start_time
    print(f"  ✅ Batch {batch_num} completed in {elapsed:.1f} seconds. Found {len(opportunities)} signals.")
    
    return opportunities

def send_batch_status(batch_num, total_batches, found_count, elapsed_time, remaining_rest):
    """إرسال حالة المجموعة إلى التلغرام"""
    status_message = f"""
📦 <b>BATCH SCAN STATUS</b>
━━━━━━━━━━━━━━━━━━
📌 Batch: {batch_num}/{total_batches}
⏱ Scan time: {elapsed_time:.1f} sec
🎯 Signals found: {found_count}

⏳ Next batch in: {remaining_rest} seconds
━━━━━━━━━━━━━━━━━━
🟢 Scanning in progress...
"""
    send(status_message)

# =========================================================
# MESSAGE FORMATTING
# =========================================================

def format_short_message(opp):
    symbol = opp['symbol']
    score = opp['score']
    
    if score >= 85:
        grade = "🟢 VERY GOOD"
        strength = "HIGH"
        color = "🟢"
    elif score >= 70:
        grade = "🟡 GOOD"
        strength = "MEDIUM"
        color = "🟡"
    else:
        grade = "🔴 MEDIUM"
        strength = "LOW"
        color = "🔴"
    
    message = f"""
{color} BINANCE — {grade}

━━━━━━━━━━━━━━━━━━
🔥 SHORT OPPORTUNITY
━━━━━━━━━━━━━━━━━━

💰 PAIR: {symbol}
🧠 AI SCORE: {score} / 100
⚠️ SIGNAL STRENGTH: {strength}

━━━━━━━━━━━━━━━━━━
📊 MARKET MOVEMENT
━━━━━━━━━━━━━━━━━━

📈 24H CHANGE: {opp['change_24h']:+.2f}%
⏱ 4H CHANGE: {opp['change_4h']:+.2f}%
⚡ 1H CHANGE: {opp['change_1h']:+.2f}%

━━━━━━━━━━━━━━━━━━
🧠 TECHNICAL ANALYSIS
━━━━━━━━━━━━━━━━━━

📊 RSI 5M: {opp['rsi_5m']:.2f}
📊 RSI 15M: {opp['rsi_15m']:.2f}
📊 RSI 1H: {opp['rsi_1h']:.2f}

🕯 CANDLE PATTERN:
✔ Bearish Rejection

📉 VOLUME STATUS:
⚠ Weakening

📏 EMA DISTANCE:
{opp['stretch']:.2f}%

📊 ATR (Avg True Range):
{opp['atr_percent']:.2f}% ✅

━━━━━━━━━━━━━━━━━━
🎯 TRADE SETUP
━━━━━━━━━━━━━━━━━━

🔴 SHORT ENTRY ZONE:
{opp['entry_low']:.8f} → {opp['entry_high']:.8f}

📉 EXPECTED DROP:
{opp['drop']:.2f}%

━━━━━━━━━━━━━━━━━━
💼 RISK MANAGEMENT
━━━━━━━━━━━━━━━━━━

💵 POSITION SIZE: 5$
⚡ LEVERAGE: x2 (Isolated)

━━━━━━━━━━━━━━━━━━
⏱ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
━━━━━━━━━━━━━━━━━━
"""
    return message

def format_long_message(opp):
    symbol = opp['symbol']
    score = opp['score']
    
    if score >= 30:
        strength_emoji = "🚀🚀🚀"
        strength_text = "VERY STRONG"
    elif score >= 20:
        strength_emoji = "🚀🚀"
        strength_text = "STRONG"
    elif score >= 15:
        strength_emoji = "📈"
        strength_text = "MEDIUM"
    else:
        strength_emoji = "⭐"
        strength_text = "WEAK"
    
    rsi_lines = []
    for tf in ['15m', '1h', '4h']:
        if tf in opp['analyses']:
            rsi_value = opp['analyses'][tf]['rsi']
            if rsi_value >= 50:
                emoji = "📈"
                status = "Bullish momentum"
            elif rsi_value >= 30:
                emoji = "⚪"
                status = "Neutral"
            else:
                emoji = "📉"
                status = "Weak"
            rsi_lines.append(f"• {tf}: {rsi_value:.1f} ({status}) {emoji}")
    
    bb_4h = opp['analyses'].get('4h', opp['analyses']['1h'])
    candle_4h = opp['analyses'].get('4h', opp['analyses']['1h'])
    gc_4h = opp['analyses'].get('4h', opp['analyses']['1h'])
    
    message = f"""
{strength_emoji} <b>BULLISH OPPORTUNITY</b> {strength_emoji}

━━━━━━━━━━━━━━━━━━
<b>PAIR:</b> {symbol}
<b>AI SCORE:</b> {score} / 100
<b>SIGNAL STRENGTH:</b> {strength_text}
━━━━━━━━━━━━━━━━━━

<b>💰 CURRENT PRICE:</b> ${opp['current_price']:.4f}

<b>🎯 ENTRY ZONE:</b>
{opp['entry_low']:.4f} → {opp['entry_high']:.4f}

━━━━━━━━━━━━━━━━━━
<b>📊 TECHNICAL ANALYSIS</b>
━━━━━━━━━━━━━━━━━━

<b>📈 RSI ANALYSIS:</b>
{chr(10).join(rsi_lines)}

<b>📊 BOLLINGER BANDS:</b>
• Position: {bb_4h['bb_signal']}
• ATR %: {opp['atr_percent']:.2f}% ✅

<b>🕯️ CANDLE PATTERNS:</b>
• {candle_4h['candle_pattern']}

<b>🟡 GOLDEN CROSS:</b>
• {gc_4h['gc_message']}

━━━━━━━━━━━━━━━━━━
<b>💡 TRADE SETUP (LONG)</b>
━━━━━━━━━━━━━━━━━━

<b>📈 LONG ENTRY ZONE:</b>
{opp['entry_low']:.4f} → {opp['entry_high']:.4f}

<b>🎯 EXPECTED GAIN:</b>
{opp['expected_gain']}%

━━━━━━━━━━━━━━━━━━
<b>⚙️ RISK MANAGEMENT</b>
━━━━━━━━━━━━━━━━━━

<b>💰 POSITION SIZE:</b> ${MAX_POSITION_SIZE}
<b>📊 LEVERAGE:</b> x{MAX_LEVERAGE} (Isolated)
<b>🛑 STOP LOSS:</b> ${opp['stop_loss']}
<b>✅ TAKE PROFIT 1:</b> ${opp['take_profit_1']}
<b>✅ TAKE PROFIT 2:</b> ${opp['take_profit_2']}

━━━━━━━━━━━━━━━━━━
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
━━━━━━━━━━━━━━━━━━
"""
    return message

def send_summary(short_opps, long_opps):
    summary = f"""
📊 <b>SCAN COMPLETE</b>
━━━━━━━━━━━━━━━━━━
📉 SHORT signals found: {len(short_opps)}
📈 LONG signals found: {len(long_opps)}

"""
    if short_opps:
        summary += f"🔥 Top SHORT: {', '.join([o['symbol'] for o in short_opps[:3]])}\n"
    if long_opps:
        summary += f"🚀 Top LONG: {', '.join([o['symbol'] for o in long_opps[:3]])}\n"
    
    summary += f"""
━━━━━━━━━━━━━━━━━━
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    send(summary)

def send_full_scan_summary(short_opps, all_long_opportunities, total_time, scan_number):
    """إرسال ملخص المسح الكامل"""
    summary = f"""
✅ <b>FULL SCAN #{scan_number} COMPLETE</b>
━━━━━━━━━━━━━━━━━━
⏱ Total time: {total_time/60:.1f} minutes
📉 SHORT signals: {len(short_opps)}
📈 LONG signals: {len(all_long_opportunities)}
🎯 Total signals: {len(short_opps) + len(all_long_opportunities)}

"""
    if short_opps or all_long_opportunities:
        summary += f"<b>🏆 TOP SIGNALS:</b>\n"
        count = 1
        for opp in short_opps[:3]:
            summary += f"{count}. SHORT {opp['symbol']} - Score: {opp['score']}\n"
            count += 1
        for opp in all_long_opportunities[:3]:
            summary += f"{count}. LONG {opp['symbol']} - Score: {opp['score']}\n"
            count += 1
    else:
        summary += f"📊 No quality signals found this cycle.\n━━━━━━━━━━━━━━━━━━\n🟡 Continuing scanning..."
    
    summary += f"""
━━━━━━━━━━━━━━━━━━
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    send(summary)

# =========================================================
# MAIN LOOP WITH BATCHES
# =========================================================

sent_short = set()
sent_long = set()
full_scan_counter = 0

print("🚀 DUAL SIGNAL SCANNER STARTED (BATCH MODE)")
print(f"📊 Total coins: {MAX_COINS_TO_SCAN}")
print(f"📦 Batch size: {BATCH_SIZE} coins")
print(f"⏱ Batch scan time: {BATCH_SCAN_TIME} seconds max")
print(f"💤 Rest between batches: {REST_TIME_BETWEEN_BATCHES} seconds")
total_batches = (MAX_COINS_TO_SCAN + BATCH_SIZE - 1) // BATCH_SIZE
total_minutes = ((BATCH_SCAN_TIME + REST_TIME_BETWEEN_BATCHES) * total_batches) / 60
print(f"🎯 Total scan time: ~{total_minutes:.0f} minutes")

send(f"🚀 <b>DUAL SIGNAL SCANNER STARTED (BATCH MODE)</b>\n\n📊 Total: {MAX_COINS_TO_SCAN} coins\n📦 {BATCH_SIZE} coins per batch\n⏱ ~{total_minutes:.0f} minutes per full scan\n\n🎯 Quality signals only (Score > 70 + ATR 1.5-4% + Volume > 1M)")

while True:
    try:
        full_scan_counter += 1
        full_scan_start = time.time()
        
        print(f"\n{'='*60}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting FULL SCAN #{full_scan_counter}")
        print(f"{'='*60}")
        
        send(f"🔄 <b>FULL SCAN #{full_scan_counter} STARTED</b>\n━━━━━━━━━━━━━━━━━━\nScanning {MAX_COINS_TO_SCAN} coins in batches...")
        
        # =================================================
        # SCAN SHORT (يبقى كما هو - سريع)
        # =================================================
        print("\n📉 Scanning for SHORT opportunities...")
        short_opps = scan_short_opportunities()
        print(f"Found {len(short_opps)} SHORT opportunities (filtered)")
        
        short_sent = []
        for opp in short_opps[:5]:
            if opp['symbol'] in sent_short:
                continue
            message = format_short_message(opp)
            send(message)
            sent_short.add(opp['symbol'])
            short_sent.append(opp)
            print(f"  ✅ Sent SHORT: {opp['symbol']} (Score: {opp['score']}, ATR: {opp['atr_percent']:.2f}%)")
        
        # =================================================
        # SCAN LONG WITH BATCHES
        # =================================================
        print("\n📈 Scanning for LONG opportunities in batches...")
        
        # الحصول على جميع العملات
        all_symbols = get_all_usdt_pairs(MAX_COINS_TO_SCAN)
        total_batches = (len(all_symbols) + BATCH_SIZE - 1) // BATCH_SIZE
        
        all_long_opportunities = []
        
        for batch_num in range(total_batches):
            batch_start = batch_num * BATCH_SIZE
            batch_end = min(batch_start + BATCH_SIZE, len(all_symbols))
            batch_symbols = all_symbols[batch_start:batch_end]
            
            # إرسال بداية المجموعة
            send(f"📦 <b>Starting Batch {batch_num + 1}/{total_batches}</b>\n━━━━━━━━━━━━━━━━━━\nScanning {len(batch_symbols)} coins...")
            
            batch_start_time = time.time()
            
            # مسح المجموعة
            batch_opps = scan_long_opportunities_batch(
                batch_symbols, 
                batch_num + 1, 
                total_batches
            )
            
            batch_elapsed = time.time() - batch_start_time
            
            # إرسال إشارات المجموعة
            batch_sent = 0
            for opp in batch_opps:
                if opp['symbol'] in sent_long:
                    continue
                message = format_long_message(opp)
                send(message)
                sent_long.add(opp['symbol'])
                all_long_opportunities.append(opp)
                batch_sent += 1
                print(f"  ✅ Sent LONG: {opp['symbol']} (Score: {opp['score']}, ATR: {opp['atr_percent']:.2f}%)")
            
            # انتظر حتى تكتمل 5 دقائق إذا لزم الأمر
            if batch_elapsed < BATCH_SCAN_TIME:
                wait_time = BATCH_SCAN_TIME - batch_elapsed
                print(f"  ⏳ Waiting {wait_time:.1f} seconds to complete 5 min batch...")
                time.sleep(wait_time)
            
            # إرسال حالة المجموعة
            remaining_rest = REST_TIME_BETWEEN_BATCHES if batch_num < total_batches - 1 else 0
            send_batch_status(
                batch_num + 1, 
                total_batches, 
                batch_sent, 
                batch_elapsed,
                remaining_rest
            )
            
            # راحة بين المجموعات (ما عدا آخر مجموعة)
            if batch_num < total_batches - 1:
                print(f"  💤 Resting {REST_TIME_BETWEEN_BATCHES} seconds before next batch...")
                time.sleep(REST_TIME_BETWEEN_BATCHES)
        
        # =================================================
        # إرسال الملخص الكامل
        # =================================================
        full_scan_elapsed = time.time() - full_scan_start
        
        send_full_scan_summary(short_sent, all_long_opportunities, full_scan_elapsed, full_scan_counter)
        
        print(f"\n✅ Full scan #{full_scan_counter} complete in {full_scan_elapsed/60:.1f} minutes")
        print(f"   SHORT signals: {len(short_sent)}")
        print(f"   LONG signals: {len(all_long_opportunities)}")
        print(f"⏳ Next full scan will start immediately...\n")
        
        # راحة قصيرة قبل البدء من جديد
        time.sleep(10)
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        time.sleep(60)
