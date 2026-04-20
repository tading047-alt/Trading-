"""
نظام التداول الورقي المتكامل - الإصدار النهائي مع تجنب Rate Limit
============================================================================
التحسينات المدمجة:
- مؤشر TSI للزخم غير المتأخر
- فلتر ميل EMA لتأكيد الاختراقات
- محاكاة OBI باستخدام بيانات Bid/Ask
- وقف خسارة متحرك معتمد على ATR (يتكيف مع تقلب العملة)
- تأمين الأرباح: نقل الوقف إلى نقطة الدخول عند ربح 2%
- تجنب العملات مرتفعة الارتفاع (>50% خلال 24 ساعة)
- آلية إعادة المحاولة (Retry Logic) لموثوقية API
- إشعار خاص للعملات التي تحقق معايير الانفجار القوي
- نظام تأكيد الزخم عبر 3 دورات متتالية
- مسح متوازي كامل (جميع العملات دفعة واحدة)
- فلترة مسبقة معززة (تغير السعر والحجم في 5 دقائق)
- نظام أولويات لتحليل العملات الساخنة أولاً
- تصنيف ذكي Gold/Silver/Bronze
- فلتر تأكيد الاختراق (يمنع الاختراقات الكاذبة)
- نظام الثقة التراكمي (Confidence Scoring)
- حجم صفقة متكيف مع درجة الثقة
- ⭐ تحسينات Rate Limit: تأخير بين الطلبات، تقليل عدد العملات، زيادة فترات المسح
"""

import asyncio
import ccxt.async_support as ccxt_async
import ccxt
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import json
import os
import csv
import shutil
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# =========================================================
# إعدادات تيليجرام
# =========================================================
TELEGRAM_TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
PUBLIC_CHAT_ID = "-1003692815602"
PRIVATE_USER_ID = "5067771509"

telegram_app = None

# =========================================================
# إعدادات التداول
# =========================================================
INITIAL_CAPITAL = 1000
MAX_POSITIONS = 10
MIN_APPEARANCES = 3
TOP_CANDIDATES_COUNT = 5

# ⭐ إعدادات المسح (مخففة لتجنب Rate Limit)
GOLD_SCAN_INTERVAL = 300    # 5 دقائق (كان 180)
SILVER_SCAN_INTERVAL = 900  # 15 دقيقة (كان 600)
BRONZE_SCAN_INTERVAL = 1800 # 30 دقيقة

GOLD_COUNT = 50     # كان 80
SILVER_COUNT = 120  # كان 200
BRONZE_COUNT = 250  # كان 500

PRICE_UPDATE_INTERVAL = 60  # تحديث الأسعار كل دقيقة (كان 30)

# عتبات تقييم النتائج
FAIL_THRESHOLD = -0.03
SUCCESS_THRESHOLD = 0.06
MAX_AGE_HOURS = 24

# إعدادات الثقة
MIN_CONFIDENCE_TO_TRADE = 30
CONFIDENCE_HIGH = 70
CONFIDENCE_MEDIUM = 50

# متغيرات الإيقاف
is_paused = False
pause_until_time = None
auto_paused_reason = None

# متغيرات عامة
all_symbols = []
gold_symbols = []
silver_symbols = []
bronze_symbols = []
symbol_classification_time = 0

# التخزين المؤقت للتحليل
analysis_cache = {}

# ⭐ نظام مراقبة Rate Limit
api_requests_count = 0
api_requests_reset_time = time.time()
MAX_REQUESTS_PER_MINUTE = 120  # هامش أمان (الحد الرسمي 200)

def can_make_request():
    global api_requests_count, api_requests_reset_time
    if time.time() - api_requests_reset_time >= 60:
        api_requests_count = 0
        api_requests_reset_time = time.time()
    if api_requests_count >= MAX_REQUESTS_PER_MINUTE:
        return False
    api_requests_count += 1
    return True

async def wait_for_rate_limit():
    """انتظار حتى يسمح Rate Limit بعمل طلب جديد"""
    while not can_make_request():
        await asyncio.sleep(0.5)
    return True

# =========================================================
# دوال تيليجرام
# =========================================================
async def send_telegram_message(text: str, to_public: bool = True, to_private: bool = True):
    global telegram_app
    if not telegram_app or not TELEGRAM_TOKEN:
        print("⚠️ تيليجرام غير مهيأ")
        return
    targets = []
    if to_public and PUBLIC_CHAT_ID:
        targets.append(PUBLIC_CHAT_ID)
    if to_private and PRIVATE_USER_ID:
        targets.append(PRIVATE_USER_ID)
    for chat_id in targets:
        try:
            await telegram_app.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            print(f"خطأ في إرسال رسالة إلى {chat_id}: {e}")

async def send_csv_file(file_path: str, caption: str = ""):
    global telegram_app
    if not telegram_app or not os.path.exists(file_path):
        return
    targets = []
    if PUBLIC_CHAT_ID:
        targets.append(PUBLIC_CHAT_ID)
    if PRIVATE_USER_ID:
        targets.append(PRIVATE_USER_ID)
    for chat_id in targets:
        try:
            with open(file_path, 'rb') as f:
                await telegram_app.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    filename=os.path.basename(file_path),
                    caption=caption
                )
        except Exception as e:
            print(f"خطأ في إرسال ملف إلى {chat_id}: {e}")

# =========================================================
# نسخ احتياطي
# =========================================================
def backup_files():
    backup_dir = "backups"
    os.makedirs(backup_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    files_to_backup = ["closed_trades.csv", "hourly_report.csv", "scan_candidates.csv", "paper_trader_state.json"]
    for file in files_to_backup:
        if os.path.exists(file):
            shutil.copy(file, f"{backup_dir}/{date_str}_{file}")
    print(f"✅ نسخ احتياطي في {backup_dir}")

# =========================================================
# آلية إعادة المحاولة (مع تأخير أطول)
# =========================================================
async def fetch_with_retry(func, *args, max_retries=3, delay=5, **kwargs):
    for attempt in range(max_retries):
        try:
            await wait_for_rate_limit()
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            print(f"⚠️ محاولة {attempt+1} فشلت: {e}. إعادة المحاولة بعد {delay} ثانية...")
            await asyncio.sleep(delay)
    return None

# =========================================================
# المؤشرات الفنية
# =========================================================
def manual_ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def manual_rsi(close, length=14):
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=length).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=length).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def manual_macd(close, fast=12, slow=26, signal=9):
    ema_fast = manual_ema(close, fast)
    ema_slow = manual_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = manual_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def manual_atr(high, low, close, length=14):
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=length).mean()
    return atr

def manual_bollinger_bands(close, length=20, std=2):
    middle = close.rolling(window=length).mean()
    std_dev = close.rolling(window=length).std()
    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)
    return upper, middle, lower

def manual_adx(high, low, close, length=14):
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=length).mean()
    up_move = high - high.shift()
    down_move = low.shift() - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    plus_di = 100 * pd.Series(plus_dm).rolling(window=length).mean() / atr
    minus_di = 100 * pd.Series(minus_dm).rolling(window=length).mean() / atr
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(window=length).mean()
    return adx

def manual_donchian(high, low, length=20):
    upper = high.rolling(window=length).max()
    lower = low.rolling(window=length).min()
    middle = (upper + lower) / 2
    return upper, lower, middle

def manual_tsi(close, r=25, s=13):
    momentum = close.diff(1)
    abs_momentum = abs(momentum)
    ema_mom = manual_ema(momentum, r)
    ema_abs = manual_ema(abs_momentum, r)
    ema_mom2 = manual_ema(ema_mom, s)
    ema_abs2 = manual_ema(ema_abs, s)
    tsi = 100 * (ema_mom2 / ema_abs2)
    return tsi

def get_ema_slope(close, length=20, periods=3):
    ema = manual_ema(close, length)
    if len(ema) < periods:
        return 0
    slope = (ema.iloc[-1] - ema.iloc[-periods]) / periods
    return slope

# =========================================================
# فلتر تأكيد الاختراق
# =========================================================
def check_breakout_confirmation(df):
    if len(df) < 3:
        return False, 0
    
    resistance = df['high'].rolling(20).max().iloc[-3]
    breakout_candle = df.iloc[-2]
    confirmation_candle = df.iloc[-1]
    
    if breakout_candle['close'] <= resistance:
        return False, 0
    
    if confirmation_candle['low'] < resistance * 0.99:
        return False, 0
    
    avg_vol = df['volume'].rolling(20).mean().iloc[-1]
    if confirmation_candle['volume'] < avg_vol * 0.7:
        return False, 0
    
    confirmation_strength = (confirmation_candle['close'] - resistance) / resistance * 100
    return True, confirmation_strength

# =========================================================
# نظام الثقة التراكمي
# =========================================================
def calculate_confidence_score(candidate, market_context, breakout_confirmed=False, breakout_strength=0):
    confidence = 0
    
    filter_score = candidate.get('filter_score', 0)
    if filter_score >= 70:
        confidence += 30
    elif filter_score >= 50:
        confidence += 22
    elif filter_score >= 35:
        confidence += 15
    elif filter_score >= 20:
        confidence += 8
    
    if breakout_confirmed:
        confidence += 20
        if breakout_strength > 2:
            confidence += 5
    elif candidate.get('volume_confirm', False) and candidate.get('trend_confirm', False):
        confidence += 18
    elif candidate.get('volume_confirm', False):
        confidence += 10
    
    strategy_points = candidate.get('strategy_points', 0)
    if strategy_points >= 6:
        confidence += 20
    elif strategy_points >= 4:
        confidence += 14
    elif strategy_points >= 2:
        confidence += 8
    
    regime = market_context.get('regime', 'CALM')
    if regime == 'HOT':
        confidence += 15
    elif regime == 'CALM':
        confidence += 10
    else:
        confidence += 3
    
    priority = candidate.get('priority', 0)
    confidence += min(priority * 2, 10)
    
    alpha = candidate.get('alpha', 0)
    if alpha >= 2.0:
        confidence += 10
    elif alpha >= 1.5:
        confidence += 6
    elif alpha >= 1.0:
        confidence += 3
    
    return min(confidence, 100)

def get_confidence_level(confidence):
    if confidence >= CONFIDENCE_HIGH:
        return "HIGH", 1.3
    elif confidence >= CONFIDENCE_MEDIUM:
        return "MEDIUM", 1.0
    elif confidence >= MIN_CONFIDENCE_TO_TRADE:
        return "LOW", 0.7
    else:
        return "REJECT", 0

# =========================================================
# فلاتر التأكيد
# =========================================================
def check_volume_confirmation(df):
    if df.empty or len(df) < 20:
        return False, 0
    last_3_volume = df['volume'].iloc[-3:].sum()
    avg_volume_20 = df['volume'].rolling(20).mean().iloc[-1]
    ratio = last_3_volume / avg_volume_20 if avg_volume_20 > 0 else 0
    return ratio > 1.5, ratio

def check_trend_confirmation(df):
    if df.empty or len(df) < 21:
        return False, 0
    ema21 = manual_ema(df['close'], length=21)
    current_price = df['close'].iloc[-1]
    ratio = current_price / ema21.iloc[-1] if ema21.iloc[-1] > 0 else 0
    return current_price > ema21.iloc[-1], ratio

# =========================================================
# شروط الانفجار الوشيك
# =========================================================
def check_explosion_criteria(candidate):
    score = 0
    details = {}
    
    details['filter_score'] = candidate.get('filter_score', 0) >= 55
    if details['filter_score']:
        score += 1
    
    details['alpha'] = candidate.get('alpha', 0) >= 1.3
    if details['alpha']:
        score += 1
    
    details['target'] = candidate.get('target_pct', 0) >= 12
    if details['target']:
        score += 1
    
    eta_bars = candidate.get('eta_bars', 999)
    details['eta'] = eta_bars and eta_bars <= 72
    if details['eta']:
        score += 1
    
    details['strategy'] = candidate.get('strategy_points', 0) >= 4
    if details['strategy']:
        score += 1
    
    return score >= 4, score, details

# =========================================================
# شروط العملة الجيدة
# =========================================================
def check_good_coin_criteria(candidate):
    criteria_met = []
    
    if candidate.get('filter_score', 0) >= 35:
        criteria_met.append("سكور فلتر ≥ 35")
    if candidate.get('alpha', 0) >= 1.0:
        criteria_met.append("سكور ألفا ≥ 1.0")
    if candidate.get('target_pct', 0) >= 8:
        criteria_met.append("هدف ≥ 8%")
    if candidate.get('strategy_points', 0) >= 2:
        criteria_met.append("نقاط استراتيجية ≥ 2")
    if candidate.get('volume_confirm', False):
        criteria_met.append("تأكيد حجم ✅")
    if candidate.get('trend_confirm', False):
        criteria_met.append("تأكيد اتجاه ✅")
    
    return len(criteria_met) >= 4, criteria_met

# =========================================================
# تأكيد الزخم متعدد الدورات
# =========================================================
def check_momentum_confirmation(tracker, min_appearances=3):
    confirmed = []
    for symbol, count in tracker.appearance_count.items():
        if count >= min_appearances:
            for cand in tracker.active_candidates:
                if cand['symbol'] == symbol and cand['status'] == 'ACTIVE':
                    confirmed.append(cand)
                    break
    return confirmed

# =========================================================
# تقييم نتيجة الصفقة
# =========================================================
def evaluate_trade_outcome(entry_price, highest_price, lowest_price, current_price):
    if entry_price <= 0:
        return "PENDING", 0
    
    high_change = (highest_price - entry_price) / entry_price
    low_change = (lowest_price - entry_price) / entry_price
    
    if high_change >= SUCCESS_THRESHOLD:
        return "SUCCESS", SUCCESS_THRESHOLD * 100
    elif low_change <= FAIL_THRESHOLD:
        return "FAIL", FAIL_THRESHOLD * 100
    else:
        current_change = (current_price - entry_price) / entry_price
        return "PENDING", current_change * 100

# =========================================================
# حساب حجم الصفقة الديناميكي
# =========================================================
def calculate_dynamic_position_size(signal_type, cash, entry_price, stop_loss, target_pct, alpha=0, confidence_multiplier=1.0):
    base_settings = {
        'explosion': {'risk': 0.04, 'multiplier': 1.5, 'max_value': 180},
        'momentum':  {'risk': 0.035, 'multiplier': 1.2, 'max_value': 130},
        'alpha':     {'risk': 0.03, 'multiplier': 1.0, 'max_value': 90}
    }
    
    settings = base_settings.get(signal_type, base_settings['alpha']).copy()
    
    if target_pct >= 25:
        settings['multiplier'] *= 1.2
    elif target_pct >= 18:
        settings['multiplier'] *= 1.1
    
    if signal_type == 'alpha' and alpha >= 2.5:
        settings['multiplier'] *= 1.2
    
    final_risk = settings['risk'] * settings['multiplier']
    final_risk = min(final_risk, 0.06)
    
    risk_amount = cash * final_risk
    risk_per_unit = abs(entry_price - stop_loss) / entry_price
    
    if risk_per_unit == 0:
        return 0
    
    position_value = risk_amount / risk_per_unit
    position_value = min(position_value, cash * 0.95)
    position_value = min(position_value, settings['max_value'])
    
    position_value = position_value * confidence_multiplier
    
    return position_value

# =========================================================
# دوال مساعدة
# =========================================================
def format_eta(eta_bars):
    if eta_bars is None:
        return "غير محدد"
    eta_minutes = eta_bars * 5
    if eta_minutes < 60:
        return f"{int(eta_minutes)} دقيقة"
    elif eta_minutes < 1440:
        return f"{eta_minutes/60:.1f} ساعة"
    else:
        return f"{eta_minutes/1440:.1f} يوم"

def fetch_ohlcv_sync(exchange, symbol, timeframe='5m', limit=40):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except:
        return pd.DataFrame()

def calculate_priority(item):
    priority = 0
    
    price_change = item.get('price_change_5m', 0)
    if abs(price_change) > 0.02:
        priority += 5
    elif abs(price_change) > 0.01:
        priority += 3
    elif abs(price_change) > 0.005:
        priority += 1
    
    volume_change = item.get('volume_change_5m', 1)
    if volume_change > 4:
        priority += 4
    elif volume_change > 2.5:
        priority += 2
    elif volume_change > 1.5:
        priority += 1
    
    if item.get('close', 0) > item.get('high_24h', 0) * 0.97:
        priority += 3
    elif item.get('close', 0) > item.get('high_24h', 0) * 0.95:
        priority += 1
    
    if item.get('volume_24h', 0) > 10_000_000:
        priority += 2
    elif item.get('volume_24h', 0) > 5_000_000:
        priority += 1
    
    if item.get('volatility', 0) > 0.05:
        priority += 2
    elif item.get('volatility', 0) > 0.03:
        priority += 1
    
    return priority

# =========================================================
# التخزين المؤقت للتحليل
# =========================================================
def get_cached_analysis(symbol, current_price):
    if symbol in analysis_cache:
        cached = analysis_cache[symbol]
        price_change = abs(current_price - cached['price']) / cached['price'] if cached['price'] > 0 else 1
        
        if price_change < 0.005 and time.time() - cached['timestamp'] < 120:
            return cached['result']
    
    return None

def cache_analysis(symbol, price, result):
    analysis_cache[symbol] = {
        'price': price,
        'result': result,
        'timestamp': time.time()
    }
    
    if len(analysis_cache) > 500:
        now = time.time()
        for sym in list(analysis_cache.keys()):
            if now - analysis_cache[sym]['timestamp'] > 300:
                del analysis_cache[sym]

# =========================================================
# تصنيف العملات
# =========================================================
async def classify_symbols(exchange, symbols):
    gold, silver, bronze = [], [], []
    
    print(f"📊 جاري تصنيف {len(symbols)} عملة...")
    
    tasks = [fetch_with_retry(exchange.fetch_ticker, sym) for sym in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for sym, res in zip(symbols, results):
        if isinstance(res, Exception) or res is None:
            bronze.append(sym)
            continue
        
        volume = res.get('quoteVolume', 0) or 0
        high = res.get('high', 0) or 0
        low = res.get('low', 0) or 0
        close = res.get('close', 0) or 1
        volatility = (high - low) / close if close > 0 else 0
        
        if volume > 5_000_000 and volatility > 0.03:
            gold.append(sym)
        elif volume > 1_000_000 and volatility > 0.02:
            silver.append(sym)
        else:
            bronze.append(sym)
    
    print(f"✅ تصنيف: 🥇 Gold={len(gold)}, 🥈 Silver={len(silver)}, 🥉 Bronze={len(bronze)}")
    return gold, silver, bronze

# =========================================================
# فلترة مسبقة معززة (مع تأخير لتجنب Rate Limit)
# =========================================================
async def enhanced_quick_filter(exchange, symbols, tier_name):
    await wait_for_rate_limit()
    
    async def fetch_symbol_data(symbol):
        try:
            await asyncio.sleep(0.15)  # ⭐ تأخير بين الطلبات
            
            ticker = await fetch_with_retry(exchange.fetch_ticker, symbol)
            ohlcv = await fetch_with_retry(exchange.fetch_ohlcv, symbol, '5m', limit=2)
            
            if len(ohlcv) < 2:
                return None
            
            last_candle = ohlcv[-1]
            prev_candle = ohlcv[-2]
            
            close = ticker.get('close', 0)
            high_24h = ticker.get('high', 0)
            low_24h = ticker.get('low', 0)
            volume_24h = ticker.get('quoteVolume', 0) or 0
            
            price_change_5m = (last_candle[4] - prev_candle[4]) / prev_candle[4] if prev_candle[4] > 0 else 0
            volume_change_5m = last_candle[5] / prev_candle[5] if prev_candle[5] > 0 else 1
            
            if volume_24h < 200000:
                return None
            if close > 0 and (high_24h - low_24h) / close < 0.015:
                return None
            
            change_24h = ticker.get('percentage', 0) or 0
            if change_24h < -10 or change_24h > 40:
                return None
            
            bid = ticker.get('bid', 0) or 0
            ask = ticker.get('ask', 0) or 0
            if ask > 0 and (ask - bid) / ask > 0.005:
                return None
            
            if abs(price_change_5m) < 0.003 and volume_change_5m < 1.3:
                return None
            
            bid_volume = ticker.get('bidVolume', 0) or 0
            ask_volume = ticker.get('askVolume', 0) or 0
            obi = (bid_volume - ask_volume) / (bid_volume + ask_volume) if (bid_volume + ask_volume) > 0 else 0
            
            return {
                'symbol': symbol,
                'close': close,
                'high_24h': high_24h,
                'low_24h': low_24h,
                'volume_24h': volume_24h,
                'volatility': (high_24h - low_24h) / close if close > 0 else 0,
                'price_change_5m': price_change_5m,
                'volume_change_5m': volume_change_5m,
                'change_24h': change_24h,
                'obi': obi
            }
        except:
            return None
    
    tasks = [fetch_symbol_data(sym) for sym in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    passed = []
    for res in results:
        if res is not None and not isinstance(res, Exception):
            res['priority'] = calculate_priority(res)
            passed.append(res)
    
    passed.sort(key=lambda x: x['priority'], reverse=True)
    
    print(f"   {tier_name}: {len(passed)} عملة اجتازت الفلترة (من {len(symbols)})")
    return passed

# =========================================================
# حساب السكور والمؤشرات
# =========================================================
def calculate_filter_score(df):
    if df.empty or len(df) < 20:
        return 0
    last = df.iloc[-1]
    score = 0
    avg_vol = df['volume'].rolling(20).mean().iloc[-1]
    if pd.notna(avg_vol) and avg_vol > 0:
        vol_ratio = last['volume'] / avg_vol
        if vol_ratio > 2.0: score += 15
        if vol_ratio > 3.0: score += 15
    rsi_series = manual_rsi(df['close'], length=14)
    if not rsi_series.empty:
        rsi = rsi_series.iloc[-1]
        if pd.notna(rsi):
            if 50 < rsi < 75: score += 20
            elif rsi > 75: score += 10
    upper, _, _ = manual_donchian(df['high'], df['low'], length=20)
    if pd.notna(upper.iloc[-1]) and last['close'] > upper.iloc[-1]:
        score += 20
    macd_line, signal_line, _ = manual_macd(df['close'])
    if pd.notna(macd_line.iloc[-1]) and pd.notna(signal_line.iloc[-1]):
        if macd_line.iloc[-1] > signal_line.iloc[-1]:
            score += 15
    bb_upper, _, _ = manual_bollinger_bands(df['close'])
    if pd.notna(bb_upper.iloc[-1]) and last['close'] > bb_upper.iloc[-1]:
        score += 15
    
    tsi_series = manual_tsi(df['close'])
    if not tsi_series.empty and pd.notna(tsi_series.iloc[-1]):
        if tsi_series.iloc[-1] > 0:
            score += 10
        if tsi_series.iloc[-1] > 10:
            score += 5
    return score

def check_strategies_weighted(df, obi=0):
    points = 0
    if df.empty or len(df) < 20:
        return 0
    last = df.iloc[-1]
    avg_vol = df['volume'].rolling(20).mean().iloc[-1]
    avg_price = df['close'].rolling(20).mean().iloc[-1]
    
    if pd.notna(avg_vol) and pd.notna(avg_price) and avg_price > 0:
        if last['volume'] > avg_vol * 2.5 and abs(last['close'] - avg_price) / avg_price < 0.02:
            points += 3
    if pd.notna(avg_vol) and last['volume'] > avg_vol * 4:
        points += 3
    resistance = df['high'].rolling(20).max().iloc[-2]
    adx_series = manual_adx(df['high'], df['low'], df['close'])
    if not adx_series.empty:
        adx = adx_series.iloc[-1]
        if pd.notna(resistance) and pd.notna(adx) and pd.notna(avg_vol):
            if last['close'] > resistance and last['volume'] > avg_vol and adx > 25:
                points += 2
    ema9 = manual_ema(df['close'], length=9)
    ema21 = manual_ema(df['close'], length=21)
    if not ema9.empty and not ema21.empty:
        if ema9.iloc[-1] > ema21.iloc[-1] and ema9.iloc[-2] <= ema21.iloc[-2]:
            points += 1
    
    ema_slope = get_ema_slope(df['close'], length=20, periods=3)
    if ema_slope > 0.001:
        points += 1
    
    if obi > 0.1:
        points += 1
    elif obi > 0.2:
        points += 2
        
    return points

def calculate_enhanced_alpha(df, market_context, obi=0):
    if df.empty or len(df) < 20:
        return 0.0
    last = df.iloc[-1]
    avg_vol = df['volume'].rolling(20).mean().iloc[-1]
    vol_ratio = last['volume'] / avg_vol if avg_vol > 0 else 1.0
    atr_series = manual_atr(df['high'], df['low'], df['close'])
    atr = atr_series.iloc[-1] if not atr_series.empty else 0
    resistance = df['high'].rolling(20).max().iloc[-2]
    breakout_strength = (last['close'] - resistance) / atr if atr > 0 else 0
    
    tsi_series = manual_tsi(df['close'])
    tsi_val = tsi_series.iloc[-1] if not tsi_series.empty else 0
    tsi_signal = 1 / (1 + np.exp(-0.2 * tsi_val))
    
    def sigmoid(x, k=2): return 1 / (1 + np.exp(-k * x))
    z_vol = sigmoid(vol_ratio - 1.5, k=1.5)
    z_breakout = sigmoid(breakout_strength, k=2)
    depth_ratio = 1.0 + (vol_ratio / 10) + (obi * 2)
    z_depth = sigmoid(depth_ratio - 1.0, k=3)
    
    regime = market_context.get('regime', 'CALM')
    if regime == 'HOT':
        w_vol, w_break, w_depth, w_tsi = 0.25, 0.4, 0.15, 0.2
    elif regime == 'COLD':
        w_vol, w_break, w_depth, w_tsi = 0.2, 0.3, 0.3, 0.2
    else:
        w_vol, w_break, w_depth, w_tsi = 0.3, 0.3, 0.2, 0.2
    
    raw_alpha = (z_vol * w_vol) + (z_breakout * w_break) + (z_depth * w_depth) + (tsi_signal * w_tsi)
    beta_adj = -0.05 if regime == 'COLD' else (0.03 if regime == 'HOT' else 0.0)
    return round(raw_alpha + beta_adj, 4)

def calculate_target_percentage(df):
    if df.empty or len(df) < 20:
        return 5.0
    last = df.iloc[-1]
    highs = df['high'].rolling(50).max().dropna().unique()
    highs_sorted = sorted(highs, reverse=True)
    target_sr = None
    for h in highs_sorted:
        if h > last['close'] * 1.02:
            target_sr = h
            break
    sr_pct = ((target_sr - last['close']) / last['close']) * 100 if target_sr else 8.0
    atr_series = manual_atr(df['high'], df['low'], df['close'])
    atr = atr_series.iloc[-1] if not atr_series.empty else last['close'] * 0.02
    atr_pct = (atr * 2.5 / last['close']) * 100
    high_20 = df['high'].rolling(20).max().iloc[-1]
    low_20 = df['low'].rolling(20).min().iloc[-1]
    fib_target = high_20 + (high_20 - low_20) * 0.618
    fib_pct = ((fib_target - last['close']) / last['close']) * 100 if fib_target > last['close'] else sr_pct
    blended = (sr_pct * 0.4) + (atr_pct * 0.3) + (fib_pct * 0.3)
    return min(blended, 40.0)

def calculate_blended_eta(df, target_price):
    if df.empty or len(df) < 15:
        return None
    current_price = df['close'].iloc[-1]
    distance = target_price - current_price
    if distance <= 0:
        return 0
    atr_series = manual_atr(df['high'], df['low'], df['close'])
    atr = atr_series.iloc[-1] if not atr_series.empty else 0
    eta_atr = distance / atr if atr > 0 else float('inf')
    lookback = 4
    if len(df) > lookback:
        speed = (current_price - df['close'].iloc[-lookback-1]) / lookback
        eta_speed = distance / speed if speed > 0 else float('inf')
    else:
        eta_speed = float('inf')
    blended_bars = (eta_atr * 0.6) + (eta_speed * 0.4) if eta_speed < eta_atr * 2 else eta_atr
    if len(df) > 15:
        atr_prev = atr_series.iloc[-2]
        if atr_prev > 0 and atr / atr_prev > 1.2:
            blended_bars *= 0.8
    return max(blended_bars, 1)

def detect_market_regime(exchange):
    try:
        df_btc = fetch_ohlcv_sync(exchange, 'BTC/USDT', '1h', 24)
        if df_btc.empty:
            return {'regime': 'CALM', 'volatility': 0.02}
        returns = df_btc['close'].pct_change().dropna()
        volatility = returns.std() * np.sqrt(24)
        slope = np.polyfit(np.arange(len(df_btc)), df_btc['close'], 1)[0]
        trend = slope / df_btc['close'].mean()
        avg_vol = df_btc['volume'].rolling(6).mean().iloc[-1]
        cur_vol = df_btc['volume'].iloc[-1]
        vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 1.0
        if volatility > 0.04 or vol_ratio > 1.8:
            regime = "HOT"
        elif trend < -0.015:
            regime = "COLD"
        else:
            regime = "CALM"
        return {'regime': regime, 'volatility': volatility}
    except:
        return {'regime': 'CALM', 'volatility': 0.02}

# =========================================================
# متتبع الترشيحات
# =========================================================
class CandidateTracker:
    def __init__(self):
        self.candidates_csv = "scan_candidates.csv"
        self.active_candidates = []
        self.appearance_count = {}
        self._init_csv()

    def _init_csv(self):
        if not os.path.exists(self.candidates_csv):
            with open(self.candidates_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'Scan Time', 'Symbol', 'Rank', 'Entry Price', 'Current Price', 'Change %',
                    'Highest Price', 'Lowest Price', 'Stop Loss', 'Take Profit', 'Target %', 'Alpha',
                    'Filter Score', 'Strategy Points', 'Confidence', 'Tier', 'Priority', 'Status', 
                    'Close Time', 'Evaluation', 'Virtual PNL %'
                ])

    def add_candidates(self, candidates_list, scan_time, tier="Gold"):
        for cand in candidates_list[:TOP_CANDIDATES_COUNT]:
            symbol = cand['symbol']
            self.appearance_count[symbol] = self.appearance_count.get(symbol, 0) + 1
        
        current_symbols = {c['symbol'] for c in candidates_list[:TOP_CANDIDATES_COUNT]}
        for symbol in list(self.appearance_count.keys()):
            if symbol not in current_symbols:
                self.appearance_count[symbol] = 0
        
        for rank, cand in enumerate(candidates_list[:TOP_CANDIDATES_COUNT], 1):
            entry_price = cand['entry_price']
            record = {
                'scan_time': scan_time,
                'symbol': cand['symbol'],
                'rank': rank,
                'entry_price': entry_price,
                'current_price': entry_price,
                'change_pct': 0,
                'highest_price': entry_price,
                'lowest_price': entry_price,
                'stop_loss': cand.get('stop_loss', entry_price * 0.95),
                'take_profit': cand.get('take_profit', entry_price * 1.06),
                'target_pct': cand.get('target_pct', 0),
                'alpha': cand.get('alpha', 0),
                'filter_score': cand.get('filter_score', 0),
                'strategy_points': cand.get('strategy_points', 0),
                'confidence': cand.get('confidence', 0),
                'tier': tier,
                'priority': cand.get('priority', 0),
                'status': 'ACTIVE',
                'close_time': None,
                'evaluation': 'PENDING',
                'virtual_pnl': 0
            }
            self.active_candidates.append(record)
            self._write_record(record)

    def update_prices(self, exchange_sync):
        updated_count = 0
        for cand in self.active_candidates:
            if cand['status'] != 'ACTIVE':
                continue
            try:
                ticker = exchange_sync.fetch_ticker(cand['symbol'])
                if ticker and ticker.get('last'):
                    current_price = ticker['last']
                    cand['current_price'] = current_price
                    cand['change_pct'] = ((current_price - cand['entry_price']) / cand['entry_price']) * 100
                    
                    if current_price > cand['highest_price']:
                        cand['highest_price'] = current_price
                    if current_price < cand['lowest_price']:
                        cand['lowest_price'] = current_price
                    
                    updated_count += 1
            except:
                pass
        
        if updated_count > 0:
            print(f"📊 تم تحديث أسعار {updated_count} عملة مرشحة")

    def evaluate_and_close(self):
        now = datetime.now()
        for cand in self.active_candidates:
            if cand['status'] != 'ACTIVE':
                continue
            
            evaluation, pnl = evaluate_trade_outcome(
                cand['entry_price'], cand['highest_price'], 
                cand['lowest_price'], cand['current_price']
            )
            
            age = (now - cand['scan_time']).total_seconds() / 3600
            
            if evaluation == "SUCCESS":
                cand['status'] = 'CLOSED'
                cand['close_time'] = now
                cand['evaluation'] = 'SUCCESS'
                cand['virtual_pnl'] = SUCCESS_THRESHOLD * 100
                self._write_record(cand)
                print(f"✅ {cand['symbol']} حققت نجاح (+6%)")
            elif evaluation == "FAIL":
                cand['status'] = 'CLOSED'
                cand['close_time'] = now
                cand['evaluation'] = 'FAIL'
                cand['virtual_pnl'] = FAIL_THRESHOLD * 100
                self._write_record(cand)
                print(f"❌ {cand['symbol']} فشلت (-3%)")
            elif age >= MAX_AGE_HOURS:
                cand['status'] = 'CLOSED'
                cand['close_time'] = now
                cand['evaluation'] = 'EXPIRED'
                cand['virtual_pnl'] = cand['change_pct']
                self._write_record(cand)
            else:
                cand['evaluation'] = 'PENDING'
                cand['virtual_pnl'] = cand['change_pct']
                self._write_record(cand)
        
        self.active_candidates = [c for c in self.active_candidates if c['status'] == 'ACTIVE']

    def _write_record(self, record):
        with open(self.candidates_csv, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                record['scan_time'].isoformat(),
                record['symbol'],
                record['rank'],
                f"{record['entry_price']:.4f}",
                f"{record['current_price']:.4f}",
                f"{record['change_pct']:.2f}%",
                f"{record['highest_price']:.4f}",
                f"{record['lowest_price']:.4f}",
                f"{record['stop_loss']:.4f}",
                f"{record['take_profit']:.4f}",
                f"{record['target_pct']:.2f}%",
                f"{record['alpha']:.3f}",
                record['filter_score'],
                record['strategy_points'],
                record['confidence'],
                record['tier'],
                record['priority'],
                record['status'],
                record['close_time'].isoformat() if record['close_time'] else '',
                record['evaluation'],
                f"{record['virtual_pnl']:.2f}%"
            ])

    def get_statistics(self):
        if not os.path.exists(self.candidates_csv):
            return None
        df = pd.read_csv(self.candidates_csv)
        closed = df[df['Status'] == 'CLOSED']
        if len(closed) == 0:
            return None
        success = closed[closed['Evaluation'] == 'SUCCESS']
        fail = closed[closed['Evaluation'] == 'FAIL']
        return {
            'total': len(closed),
            'success': len(success),
            'fail': len(fail),
            'success_rate': (len(success) / len(closed)) * 100 if len(closed) > 0 else 0
        }

# =========================================================
# نظام التداول الورقي
# =========================================================
class PaperTrader:
    def __init__(self, initial_capital=1000, max_positions=10):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.max_positions = max_positions
        self.positions = []
        self.closed_trades = []
        self.data_file = "paper_trader_state.json"
        self.trades_csv = "closed_trades.csv"
        self.report_csv = "hourly_report.csv"
        self.load_state()
        self._init_csv_files()

    def _init_csv_files(self):
        if not os.path.exists(self.trades_csv):
            with open(self.trades_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Symbol', 'Entry Price', 'Exit Price', 'Amount', 'Entry Time', 'Exit Time',
                                 'PNL ($)', 'PNL (%)', 'Exit Reason', 'Alpha', 'Target %', 'ETA', 
                                 'Signal Type', 'Confidence'])
        if not os.path.exists(self.report_csv):
            with open(self.report_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Timestamp', 'Cash', 'Total PNL', 'Return %', 'Total Trades',
                                 'Wins', 'Losses', 'Win Rate %', 'Open Positions'])

    def load_state(self):
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    self.cash = data.get('cash', self.initial_capital)
                    self.closed_trades = data.get('closed_trades', [])
                    print(f"📂 تم تحميل الحالة: الرصيد = {self.cash:.2f}$")
            except:
                print("⚠️ بدء محفظة جديدة")

    def save_state(self):
        data = {'cash': self.cash, 'closed_trades': self.closed_trades, 'positions': self.positions}
        with open(self.data_file, 'w') as f:
            json.dump(data, f, indent=2)

    def _append_trade_to_csv(self, trade):
        with open(self.trades_csv, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                trade['symbol'],
                f"{trade['entry_price']:.4f}",
                f"{trade['exit_price']:.4f}",
                f"{trade['amount']:.4f}",
                trade['entry_time'],
                trade['exit_time'],
                f"{trade['pnl']:.2f}",
                f"{trade['pnl_pct']:.2f}",
                trade['exit_reason'],
                f"{trade.get('alpha', 0):.3f}",
                f"{trade.get('target_pct', 0):.2f}",
                trade.get('eta_str', 'N/A'),
                trade.get('signal_type', 'unknown'),
                trade.get('confidence', 0)
            ])

    def open_position(self, signal, exchange, signal_type='alpha', confidence=50, confidence_multiplier=1.0):
        symbol = signal['symbol']
        entry_price = signal['entry_price']
        target_pct = signal['target_pct']
        alpha = signal['alpha']
        eta_str = signal.get('eta_str', 'غير محدد')
        df = signal.get('df')

        if df is not None and len(df) > 14:
            atr_series = manual_atr(df['high'], df['low'], df['close'])
            atr = atr_series.iloc[-1] if not atr_series.empty else entry_price * 0.03
        else:
            atr = entry_price * 0.03
        
        volatility_pct = atr / entry_price
        if volatility_pct > 0.15:
            print(f"⚠️ تقلب عالي ({volatility_pct*100:.1f}%)، تخطي {symbol}")
            return False
        
        atr_multiplier = 3.0
        stop_loss = entry_price - (atr_multiplier * atr)
        take_profit = entry_price * (1 + target_pct / 100)
        
        position_value = calculate_dynamic_position_size(
            signal_type, self.cash, entry_price, stop_loss, target_pct, alpha, confidence_multiplier
        )
        
        if position_value <= 0:
            return False
            
        amount = position_value / entry_price
        
        try:
            market = exchange.market(symbol)
            min_amount = market['limits']['amount']['min']
            if amount < min_amount:
                amount = min_amount
                position_value = amount * entry_price
        except:
            pass

        if len(self.positions) >= self.max_positions or position_value > self.cash:
            return False
        for pos in self.positions:
            if pos['symbol'] == symbol:
                return False

        self.cash -= position_value
        position = {
            'symbol': symbol,
            'entry_price': entry_price,
            'amount': amount,
            'position_value': position_value,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'entry_time': datetime.now(),
            'alpha': alpha,
            'target_pct': target_pct,
            'eta_str': eta_str,
            'highest_price': entry_price,
            'atr_value': atr,
            'breakeven_activated': False,
            'current_stop': stop_loss,
            'signal_type': signal_type,
            'confidence': confidence
        }
        self.positions.append(position)

        confidence_tag = "🟢" if confidence >= CONFIDENCE_HIGH else ("🟡" if confidence >= CONFIDENCE_MEDIUM else "🟠")
        msg = (f"{confidence_tag} صفقة جديدة ({signal_type}، ثقة {confidence}%): {symbol}\n"
               f"سعر الدخول: {entry_price:.4f}\n"
               f"قيمة الصفقة: {position_value:.2f}$\n"
               f"كمية: {amount:.4f}\n"
               f"🛑 وقف الخسارة: {stop_loss:.4f}\n"
               f"🎯 جني الأرباح: {take_profit:.4f}\n"
               f"📈 نسبة الصعود: {target_pct:.2f}%\n"
               f"⏱️ الوقت المتوقع: {eta_str}\n"
               f"⭐ سكور ألفا: {alpha:.3f}\n"
               f"💰 الرصيد المتبقي: {self.cash:.2f}$")
        print(msg)
        asyncio.create_task(send_telegram_message(msg))
        self.save_state()
        return True

    def update_positions(self, current_prices):
        to_close = []
        for i, pos in enumerate(self.positions):
            symbol = pos['symbol']
            if symbol not in current_prices:
                continue
            price = current_prices[symbol]
            
            if price > pos['highest_price']:
                pos['highest_price'] = price
            
            atr_value = pos.get('atr_value', price * 0.03)
            atr_multiplier = 2.5
            
            trailing_stop = pos['highest_price'] - (atr_multiplier * atr_value)
            
            if not pos['breakeven_activated'] and price >= pos['entry_price'] * 1.02:
                pos['breakeven_activated'] = True
                trailing_stop = max(trailing_stop, pos['entry_price'])
            
            if trailing_stop > pos['current_stop']:
                pos['current_stop'] = trailing_stop
            
            final_stop = pos['current_stop']
            
            if price <= final_stop:
                reason = "وقف خسارة متحرك"
                if pos['breakeven_activated'] and final_stop >= pos['entry_price']:
                    reason = "وقف خسارة متحرك (نقطة التعادل)"
                to_close.append((i, price, reason))
            elif price <= pos['stop_loss']:
                to_close.append((i, price, "وقف خسارة أولي"))
            elif price >= pos['take_profit']:
                to_close.append((i, price, "جني أرباح"))
                
        for i, price, reason in sorted(to_close, key=lambda x: x[0], reverse=True):
            self.close_position(i, price, reason)

    def close_position(self, index, exit_price, reason):
        pos = self.positions.pop(index)
        exit_value = pos['amount'] * exit_price
        pnl = exit_value - pos['position_value']
        pnl_pct = (pnl / pos['position_value']) * 100
        self.cash += exit_value
        trade_record = {
            'symbol': pos['symbol'],
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'amount': pos['amount'],
            'entry_time': pos['entry_time'].isoformat(),
            'exit_time': datetime.now().isoformat(),
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'exit_reason': reason,
            'alpha': pos.get('alpha', 0),
            'target_pct': pos.get('target_pct', 0),
            'eta_str': pos.get('eta_str', 'N/A'),
            'signal_type': pos.get('signal_type', 'unknown'),
            'confidence': pos.get('confidence', 0)
        }
        self.closed_trades.append(trade_record)
        self._append_trade_to_csv(trade_record)
        msg = f"🔴 إغلاق {pos['symbol']}: {reason} | ربح = {pnl:.2f}$ ({pnl_pct:.2f}%) | الرصيد = {self.cash:.2f}$"
        print(msg)
        asyncio.create_task(send_telegram_message(msg))
        self.save_state()

    def get_stats(self):
        if not self.closed_trades:
            return None
        wins = [t for t in self.closed_trades if t['pnl'] > 0]
        losses = [t for t in self.closed_trades if t['pnl'] <= 0]
        win_rate = len(wins) / len(self.closed_trades) * 100 if self.closed_trades else 0
        total_pnl = sum(t['pnl'] for t in self.closed_trades)
        return {
            'total_trades': len(self.closed_trades),
            'win_count': len(wins),
            'loss_count': len(losses),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_return_pct': (total_pnl / self.initial_capital) * 100,
            'current_cash': self.cash,
            'open_positions': len(self.positions)
        }

    def generate_report(self, current_prices=None):
        stats = self.get_stats()
        if not stats:
            return None
        with open(self.report_csv, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(),
                f"{self.cash:.2f}",
                f"{stats['total_pnl']:.2f}",
                f"{stats['total_return_pct']:.2f}",
                stats['total_trades'],
                stats['win_count'],
                stats['loss_count'],
                f"{stats['win_rate']:.2f}",
                stats['open_positions']
            ])
        report = "📊 تقرير الأداء\n"
        report += f"💰 الرصيد: {self.cash:.2f}$ (بداية: {self.initial_capital}$)\n"
        report += f"📈 العائد: {stats['total_pnl']:.2f}$ ({stats['total_return_pct']:.2f}%)\n"
        report += f"📋 صفقات مغلقة: {stats['total_trades']} | ✅ {stats['win_count']} | ❌ {stats['loss_count']}\n"
        report += f"🎯 نسبة النجاح: {stats['win_rate']:.2f}%\n"
        report += f"🔓 صفقات مفتوحة: {stats['open_positions']}\n"
        if self.positions and current_prices:
            report += "\n📌 الصفقات المفتوحة:\n"
            for pos in self.positions:
                sym = pos['symbol']
                cp = current_prices.get(sym, pos['entry_price'])
                pnl = (cp - pos['entry_price']) * pos['amount']
                pnl_pct = ((cp / pos['entry_price']) - 1) * 100
                report += f"  - {sym}: دخول {pos['entry_price']:.4f} | حالي {cp:.4f} | {pnl:.2f}$ ({pnl_pct:.2f}%)\n"
        return report

# =========================================================
# أوامر تيليجرام
# =========================================================
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_paused, auto_paused_reason, trader_instance

    if trader_instance is None:
        await update.message.reply_text("⚠️ نظام التداول غير مهيأ.")
        return

    status_text = "🟢 نشط" if not is_paused else f"⏸️ متوقف ({auto_paused_reason or 'يدوي'})"
    stats = trader_instance.get_stats()

    if stats:
        msg = f"🤖 حالة البوت: {status_text}\n"
        msg += f"💰 الرصيد: {trader_instance.cash:.2f}$\n"
        msg += f"📈 العائد: {stats['total_pnl']:.2f}$ ({stats['total_return_pct']:.2f}%)\n"
        msg += f"📋 صفقات: {stats['total_trades']} | ✅ {stats['win_count']} | ❌ {stats['loss_count']}\n"
        msg += f"🎯 نجاح: {stats['win_rate']:.2f}% | 🔓 مفتوحة: {stats['open_positions']}"
    else:
        msg = f"🤖 حالة البوت: {status_text}\n💰 الرصيد: {trader_instance.cash:.2f}$"

    await update.message.reply_text(msg)

# =========================================================
# دالة تحليل مجموعة عملات
# =========================================================
async def analyze_symbols_with_priority(exchange_sync, filtered_items, market_ctx, tier_name, max_to_analyze=25):
    candidates = []
    
    items_to_analyze = filtered_items[:max_to_analyze]
    
    for item in items_to_analyze:
        cached = get_cached_analysis(item['symbol'], item['close'])
        if cached:
            candidates.append(cached)
            continue
        
        df = fetch_ohlcv_sync(exchange_sync, item['symbol'], '5m', 40)
        if df.empty:
            continue

        last_volume = df['volume'].iloc[-1]
        avg_volume_20 = df['volume'].rolling(20).mean().iloc[-1]
        if pd.isna(avg_volume_20) or last_volume < avg_volume_20 * 1.5:
            continue

        fs = calculate_filter_score(df)
        if fs < 15:
            continue

        obi = item.get('obi', 0)
        sp = check_strategies_weighted(df, obi)
        if sp < 2:
            continue

        vol_confirm, _ = check_volume_confirmation(df)
        if not vol_confirm:
            continue

        trend_confirm, _ = check_trend_confirmation(df)
        if not trend_confirm:
            continue

        breakout_confirmed, breakout_strength = check_breakout_confirmation(df)

        alpha = calculate_enhanced_alpha(df, market_ctx, obi)
        target_pct = calculate_target_percentage(df)
        last_price = df['close'].iloc[-1]
        target_price = last_price * (1 + target_pct / 100)
        eta_bars = calculate_blended_eta(df, target_price)
        eta_str = format_eta(eta_bars)
        final_rank = (alpha * 0.7) + (target_pct / 100 * 0.3)

        cand = {
            'symbol': item['symbol'],
            'entry_price': last_price,
            'alpha': alpha,
            'target_pct': target_pct,
            'eta_str': eta_str,
            'eta_bars': eta_bars,
            'final_rank': final_rank,
            'df': df,
            'obi': obi,
            'filter_score': fs,
            'strategy_points': sp,
            'volume_confirm': vol_confirm,
            'trend_confirm': trend_confirm,
            'tier': tier_name,
            'priority': item.get('priority', 0)
        }
        
        cand['confidence'] = calculate_confidence_score(cand, market_ctx, breakout_confirmed, breakout_strength)
        
        cache_analysis(item['symbol'], last_price, cand)
        
        candidates.append(cand)
    
    candidates.sort(key=lambda x: x['final_rank'], reverse=True)
    return candidates[:TOP_CANDIDATES_COUNT]

# =========================================================
# دالة معالجة المرشحين وفتح الصفقات
# =========================================================
async def process_candidates(candidates, trader, exchange_sync, tracker, tier_name):
    positions_opened = 0
    MAX_POSITIONS_PER_SCAN = 3 if tier_name == "Gold" else 2
    
    candidates.sort(key=lambda x: (x['confidence'], x['final_rank']), reverse=True)
    
    for cand in candidates:
        if positions_opened >= MAX_POSITIONS_PER_SCAN:
            break
        
        confidence_level, confidence_multiplier = get_confidence_level(cand['confidence'])
        if confidence_level == "REJECT":
            continue
        
        is_explosive, criteria_met, _ = check_explosion_criteria(cand)
        if is_explosive:
            msg = f"🔥🔥🔥 انفجار وشيك! ({tier_name})\n{cand['symbol']}\nسعر: {cand['entry_price']:.4f}\nألفا: {cand['alpha']:.3f}\nهدف: {cand['target_pct']:.2f}%\n✅ {criteria_met}/5 معايير\n🤖 ثقة: {cand['confidence']}% ({confidence_level})"
            asyncio.create_task(send_telegram_message(msg))

            already_open = any(p['symbol'] == cand['symbol'] for p in trader.positions)
            if not already_open and trader.cash > 50 and len(trader.positions) < trader.max_positions:
                df = cand['df']
                if df is not None and len(df) > 14:
                    atr_series = manual_atr(df['high'], df['low'], df['close'])
                    atr = atr_series.iloc[-1] if not atr_series.empty else cand['entry_price'] * 0.03
                else:
                    atr = cand['entry_price'] * 0.03
                cand['stop_loss'] = cand['entry_price'] - (3.0 * atr)
                cand['take_profit'] = cand['entry_price'] * (1 + cand['target_pct'] / 100)

                if trader.open_position(cand, exchange_sync, signal_type='explosion', 
                                       confidence=cand['confidence'], 
                                       confidence_multiplier=confidence_multiplier):
                    positions_opened += 1

    for cand in candidates:
        df = cand['df']
        if df is not None and len(df) > 14:
            atr_series = manual_atr(df['high'], df['low'], df['close'])
            atr = atr_series.iloc[-1] if not atr_series.empty else cand['entry_price'] * 0.03
        else:
            atr = cand['entry_price'] * 0.03
        cand['stop_loss'] = cand['entry_price'] - (3.0 * atr)
        cand['take_profit'] = cand['entry_price'] * (1 + cand['target_pct'] / 100)

    tracker.add_candidates(candidates, datetime.now(), tier_name)
    
    confirmed_momentum = check_momentum_confirmation(tracker, MIN_APPEARANCES)
    for cand in confirmed_momentum:
        if positions_opened >= MAX_POSITIONS_PER_SCAN:
            break
        if cand.get('tier') != tier_name:
            continue
        
        confidence_level, confidence_multiplier = get_confidence_level(cand['confidence'])
        if confidence_level == "REJECT":
            continue
            
        msg = f"🚀🚀🚀 تأكيد زخم! ({tier_name})\n{cand['symbol']} ظهرت {MIN_APPEARANCES} مرات متتالية!\nسعر: {cand['entry_price']:.4f}\nهدف: {cand['target_pct']:.2f}%\n🤖 ثقة: {cand['confidence']}%"
        asyncio.create_task(send_telegram_message(msg))

        already_open = any(p['symbol'] == cand['symbol'] for p in trader.positions)
        if not already_open and trader.cash > 50 and len(trader.positions) < trader.max_positions:
            if trader.open_position(cand, exchange_sync, signal_type='momentum',
                                   confidence=cand['confidence'],
                                   confidence_multiplier=confidence_multiplier):
                positions_opened += 1

    for cand in candidates:
        if positions_opened >= MAX_POSITIONS_PER_SCAN:
            break
        
        confidence_level, confidence_multiplier = get_confidence_level(cand['confidence'])
        if confidence_level == "REJECT":
            continue
            
        is_good, criteria_met = check_good_coin_criteria(cand)
        if is_good:
            already_open = any(p['symbol'] == cand['symbol'] for p in trader.positions)
            if not already_open and trader.cash > 50 and len(trader.positions) < trader.max_positions:
                if trader.open_position(cand, exchange_sync, signal_type='good_coin',
                                       confidence=cand['confidence'],
                                       confidence_multiplier=confidence_multiplier):
                    positions_opened += 1

    if candidates:
        msg = f"📋 أفضل {len(candidates)} ترشيحات ({tier_name}):\n\n"
        for i, c in enumerate(candidates, 1):
            confidence_tag = "🟢" if c['confidence'] >= CONFIDENCE_HIGH else ("🟡" if c['confidence'] >= CONFIDENCE_MEDIUM else "🟠")
            msg += f"{i}. {c['symbol']} | {c['entry_price']:.4f} | ألفا: {c['alpha']:.3f} | هدف: {c['target_pct']:.2f}% | {confidence_tag} {c['confidence']}%\n"
        asyncio.create_task(send_telegram_message(msg))

# =========================================================
# حلقة التداول الرئيسية
# =========================================================
async def trading_loop():
    global exchange_sync_instance, candidate_tracker
    global gold_symbols, silver_symbols, bronze_symbols, symbol_classification_time
    global is_paused, trader_instance

    exchange_async = ccxt_async.gateio({'enableRateLimit': True})
    exchange_sync = ccxt.gateio({'enableRateLimit': True})
    exchange_sync_instance = exchange_sync

    markets = await fetch_with_retry(exchange_async.load_markets)
    if markets:
        all_syms = [s for s in markets if s.endswith('/USDT') and '.d' not in s]
        gold_symbols, silver_symbols, bronze_symbols = await classify_symbols(exchange_async, all_syms)
        symbol_classification_time = time.time()
        print(f"📋 تصنيف: Gold={len(gold_symbols)}, Silver={len(silver_symbols)}, Bronze={len(bronze_symbols)}")
    else:
        print("❌ فشل تحميل العملات")
        return

    trader = PaperTrader(initial_capital=INITIAL_CAPITAL, max_positions=MAX_POSITIONS)
    trader_instance = trader
    tracker = CandidateTracker()
    candidate_tracker = tracker

    reject_reasons = {
        "volume_spike": 0, "filter_score": 0, "strategy": 0,
        "cold_market": 0, "high_change_24h": 0,
        "volume_confirm": 0, "trend_confirm": 0, "high_volatility": 0,
        "low_confidence": 0
    }

    last_report = time.time()
    last_backup = time.time()
    last_price_update = 0
    last_gold_scan = 0
    last_silver_scan = 0
    last_bronze_scan = 0

    print(f"🤖 بدء التداول بنظام Rate Limit الآمن - {datetime.now()}\n")
    await asyncio.sleep(2)
    await send_telegram_message(f"🚀 بوت التداول الآمن بدأ العمل!\n🥇 Gold: {len(gold_symbols)} عملة (كل 5 دقائق)\n🥈 Silver: {len(silver_symbols)} عملة (كل 15 دقيقة)\n🥉 Bronze: {len(bronze_symbols)} عملة (كل 30 دقيقة)\n🛡️ Rate Limit: {MAX_REQUESTS_PER_MINUTE} طلب/دقيقة")

    while True:
        try:
            current_time = time.time()
            
            if current_time - symbol_classification_time >= 21600:
                print("🔄 إعادة تصنيف العملات...")
                gold_symbols, silver_symbols, bronze_symbols = await classify_symbols(exchange_async, all_syms)
                symbol_classification_time = current_time

            if current_time - last_price_update >= PRICE_UPDATE_INTERVAL:
                tracker.update_prices(exchange_sync)
                tracker.evaluate_and_close()

                prices = {}
                for pos in trader.positions:
                    try:
                        ticker = await fetch_with_retry(exchange_sync.fetch_ticker, pos['symbol'])
                        if ticker:
                            prices[pos['symbol']] = ticker['last']
                        else:
                            prices[pos['symbol']] = pos['entry_price']
                    except:
                        prices[pos['symbol']] = pos['entry_price']
                trader.update_positions(prices)

                last_price_update = current_time

            if is_paused:
                if pause_until_time and datetime.now() >= pause_until_time:
                    is_paused = False
                    pause_until_time = None
                    auto_paused_reason = None
                    await send_telegram_message("▶️ تم استئناف التداول تلقائياً.")
                else:
                    await asyncio.sleep(5)
                    continue

            market_ctx = detect_market_regime(exchange_sync)
            
            if market_ctx.get('regime') == 'COLD':
                print("⚠️ السوق بارد (COLD)، تخطي فتح الصفقات")
                reject_reasons["cold_market"] += 1
                await asyncio.sleep(30)
                continue

            if current_time - last_gold_scan >= GOLD_SCAN_INTERVAL and gold_symbols:
                print(f"\n🥇 مسح Gold: {len(gold_symbols[:GOLD_COUNT])} عملة")
                filtered = await enhanced_quick_filter(exchange_async, gold_symbols[:GOLD_COUNT], "Gold")
                if filtered:
                    candidates = await analyze_symbols_with_priority(exchange_sync, filtered, market_ctx, "Gold", max_to_analyze=20)
                    if candidates:
                        await process_candidates(candidates, trader, exchange_sync, tracker, "Gold")
                last_gold_scan = current_time

            if current_time - last_silver_scan >= SILVER_SCAN_INTERVAL and silver_symbols:
                print(f"\n🥈 مسح Silver: {len(silver_symbols[:SILVER_COUNT])} عملة")
                filtered = await enhanced_quick_filter(exchange_async, silver_symbols[:SILVER_COUNT], "Silver")
                if filtered:
                    candidates = await analyze_symbols_with_priority(exchange_sync, filtered, market_ctx, "Silver", max_to_analyze=15)
                    if candidates:
                        await process_candidates(candidates, trader, exchange_sync, tracker, "Silver")
                last_silver_scan = current_time

            if current_time - last_bronze_scan >= BRONZE_SCAN_INTERVAL and bronze_symbols:
                print(f"\n🥉 مسح Bronze: {len(bronze_symbols[:BRONZE_COUNT])} عملة")
                filtered = await enhanced_quick_filter(exchange_async, bronze_symbols[:BRONZE_COUNT], "Bronze")
                if filtered:
                    candidates = await analyze_symbols_with_priority(exchange_sync, filtered, market_ctx, "Bronze", max_to_analyze=10)
                    if candidates:
                        await process_candidates(candidates, trader, exchange_sync, tracker, "Bronze")
                last_bronze_scan = current_time

            if current_time - last_report >= 3600:
                prices = {}
                for pos in trader.positions:
                    try:
                        ticker = await fetch_with_retry(exchange_sync.fetch_ticker, pos['symbol'])
                        if ticker:
                            prices[pos['symbol']] = ticker['last']
                    except:
                        pass

                report = trader.generate_report(prices)
                if report:
                    stats = tracker.get_statistics()
                    if stats:
                        report += f"\n📊 ترشيحات: ✅ {stats['success']} | ❌ {stats['fail']} | 🎯 {stats['success_rate']:.1f}%"
                    
                    reject_msg = f"\n📊 أسباب الرفض: حجم شمعة={reject_reasons['volume_spike']}, سكور={reject_reasons['filter_score']}, استراتيجية={reject_reasons['strategy']}, سوق بارد={reject_reasons['cold_market']}, ارتفاع>50%={reject_reasons['high_change_24h']}, حجم تراكمي={reject_reasons['volume_confirm']}, اتجاه={reject_reasons['trend_confirm']}, ثقة منخفضة={reject_reasons['low_confidence']}"
                    full_report = report + reject_msg
                    print(full_report)
                    asyncio.create_task(send_telegram_message(full_report))

                if os.path.exists(trader.trades_csv):
                    asyncio.create_task(send_csv_file(trader.trades_csv, "📁 صفقات مغلقة"))
                if os.path.exists(trader.report_csv):
                    asyncio.create_task(send_csv_file(trader.report_csv, "📁 تقرير الأداء"))
                if os.path.exists(tracker.candidates_csv):
                    asyncio.create_task(send_csv_file(tracker.candidates_csv, "📁 ترشيحات العملات"))
                
                for key in reject_reasons:
                    reject_reasons[key] = 0
                last_report = current_time

            if current_time - last_backup >= 86400:
                backup_files()
                last_backup = current_time

            await asyncio.sleep(2)

        except KeyboardInterrupt:
            print("\n👋 إيقاف...")
            await send_telegram_message("⏹️ تم إيقاف البوت.")
            break
        except Exception as e:
            print(f"❌ خطأ: {e}")
            await asyncio.sleep(30)

    await exchange_async.close()

# =========================================================
# الدالة الرئيسية
# =========================================================
async def main():
    global telegram_app
    
    telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()
    await telegram_app.initialize()
    print("🤖 تطبيق Telegram جاهز للإرسال...")
    
    telegram_app.add_handler(CommandHandler("status", status_command))
    
    await telegram_app.start()
    
    try:
        await trading_loop()
    except KeyboardInterrupt:
        print("\n👋 إيقاف...")
    finally:
        await telegram_app.stop()
        await telegram_app.shutdown()
        print("✅ تم إيقاف التطبيق")

if __name__ == "__main__":
    asyncio.run(main())
