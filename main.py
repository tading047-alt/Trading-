"""
نظام التداول الورقي المتكامل - مع تنبيهات الانحرافات + نظام كيلي + تصنيف AI
التحسينات المدمجة:
- مسح مقسم على دفعات (100 عملة/دفعة، 500 عملة/دورة)
- فلتر التقلب الحاد (يمنع الدخول إذا ATR > 10%)
- نسخ احتياطي تلقائي كل 24 ساعة
- نظام تسجيل نقاط المرشحين (تفصيل أسباب الاختيار)
- الإيقاف المؤقت الذكي (/pause, /resume, /pause_until)
- ⭐ تنبيهات الانحرافات (إيقاف تلقائي عند 5 خسائر متتالية)
- ⭐ نظام كيلي للمخاطرة (حجم صفقة ديناميكي متكيف)
- ⭐ تصنيف AI باستخدام XGBoost (يتعلم من الصفقات السابقة)
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
import pickle
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
MAX_POSITIONS = float('inf')
MIN_APPEARANCES = 3
TOP_CANDIDATES_COUNT = 5

# إعدادات المسح المقسم
BATCH_SIZE = 100
BATCH_DELAY = 2.5
SYMBOLS_PER_CYCLE = 500
SCAN_INTERVAL = 1800

# عتبات تقييم الترشيحات
FAIL_THRESHOLD = -0.03
BREAKEVEN_THRESHOLD = 0.03
SUCCESS_THRESHOLD = 0.06

# ⭐ إعدادات كيلي
KELLY_FRACTION = 0.5  # استخدام نصف كيلي للتحفظ
MIN_TRADES_FOR_KELLY = 10  # الحد الأدنى للصفقات لتفعيل كيلي

# ⭐ إعدادات الانحرافات
MAX_CONSECUTIVE_LOSSES = 5  # إيقاف بعد 5 خسائر متتالية
MAX_DRAWDOWN_PCT = 0.25  # إيقاف إذا تجاوز التراجع 25%

# ⭐ إعدادات AI
AI_MODEL_FILE = "xgboost_model.pkl"
AI_ENABLED = True
MIN_TRADES_FOR_AI = 50  # يحتاج 50 صفقة لبدء التعلم
AI_CONFIDENCE_THRESHOLD = 0.4  # الحد الأدنى للثقة لفتح صفقة

# متغيرات الإيقاف المؤقت
is_paused = False
pause_until_time = None
auto_paused_reason = None  # سبب الإيقاف التلقائي

# متغيرات المسح
current_cycle = 1
all_symbols = []

# ⭐ متغيرات AI
xgboost_model = None
model_features = [
    'filter_score', 'strategy_points', 'alpha', 'target_pct', 'eta_bars',
    'volume_ratio', 'rsi', 'tsi', 'obi', 'volatility_pct',
    'hidden_volume', 'whale_activity', 'true_breakout', 'golden_cross',
    'volume_confirm', 'trend_confirm', 'market_regime_encoded'
]

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
# ⭐ نظام تصنيف AI (XGBoost)
# =========================================================
def init_ai_model():
    """تهيئة نموذج XGBoost (بدون مكتبة خارجية، تنفيذ يدوي مبسط)"""
    global xgboost_model
    
    if os.path.exists(AI_MODEL_FILE):
        try:
            with open(AI_MODEL_FILE, 'rb') as f:
                xgboost_model = pickle.load(f)
            print(f"✅ تم تحميل نموذج AI من {AI_MODEL_FILE}")
            return True
        except:
            print("⚠️ فشل تحميل نموذج AI، سيتم إنشاء نموذج جديد")
    
    # نموذج بسيط قائم على المتوسطات (بدون مكتبة XGBoost)
    xgboost_model = {
        'feature_weights': {f: 1.0 for f in model_features},
        'min_values': {f: 0 for f in model_features},
        'max_values': {f: 1 for f in model_features},
        'trades_count': 0
    }
    return False

def prepare_ai_features(candidate, market_regime):
    """تحضير الميزات لنموذج AI"""
    features = {}
    
    # ميزات رقمية
    features['filter_score'] = candidate.get('filter_score', 0) / 100.0
    features['strategy_points'] = candidate.get('strategy_points', 0) / 10.0
    features['alpha'] = candidate.get('alpha', 0) / 3.0
    features['target_pct'] = candidate.get('target_pct', 0) / 40.0
    features['eta_bars'] = min(candidate.get('eta_bars', 48) / 48.0, 1.0)
    
    fd = candidate.get('filter_details', {})
    features['volume_ratio'] = min(fd.get('volume_ratio', 1) / 5.0, 1.0)
    features['rsi'] = fd.get('rsi', 50) / 100.0
    features['tsi'] = max(0, fd.get('tsi', 0)) / 30.0
    
    features['obi'] = candidate.get('obi', 0)
    features['volatility_pct'] = min(candidate.get('volatility_pct', 0.03) / 0.10, 1.0)
    
    sd = candidate.get('strategy_details', {})
    features['hidden_volume'] = 1.0 if sd.get('hidden_volume', False) else 0.0
    features['whale_activity'] = 1.0 if sd.get('whale_activity', False) else 0.0
    features['true_breakout'] = 1.0 if sd.get('true_breakout', False) else 0.0
    features['golden_cross'] = 1.0 if sd.get('golden_cross', False) else 0.0
    
    features['volume_confirm'] = 1.0 if candidate.get('volume_confirm', False) else 0.0
    features['trend_confirm'] = 1.0 if candidate.get('trend_confirm', False) else 0.0
    
    # ترميز حالة السوق
    regime_map = {'HOT': 1.0, 'CALM': 0.5, 'COLD': 0.0}
    features['market_regime_encoded'] = regime_map.get(market_regime.get('regime', 'CALM'), 0.5)
    
    return features

def predict_confidence(features):
    """توقع درجة الثقة باستخدام النموذج الحالي"""
    global xgboost_model
    
    if xgboost_model is None or xgboost_model['trades_count'] < MIN_TRADES_FOR_AI:
        return 0.5  # قيمة محايدة إذا لم يكتمل التدريب
    
    total_score = 0
    total_weight = 0
    
    for feature, value in features.items():
        if feature in xgboost_model['feature_weights']:
            weight = xgboost_model['feature_weights'][feature]
            
            # تطبيع القيمة
            min_val = xgboost_model['min_values'].get(feature, 0)
            max_val = xgboost_model['max_values'].get(feature, 1)
            if max_val > min_val:
                normalized = (value - min_val) / (max_val - min_val)
            else:
                normalized = 0.5
            
            total_score += normalized * weight
            total_weight += weight
    
    if total_weight == 0:
        return 0.5
    
    return total_score / total_weight

def update_ai_model(features, was_successful):
    """تحديث نموذج AI بناءً على نتيجة الصفقة"""
    global xgboost_model
    
    if xgboost_model is None:
        return
    
    xgboost_model['trades_count'] += 1
    
    # تحديث القيم الدنيا والعليا
    for feature, value in features.items():
        if feature not in xgboost_model['min_values']:
            xgboost_model['min_values'][feature] = value
            xgboost_model['max_values'][feature] = value
        else:
            xgboost_model['min_values'][feature] = min(xgboost_model['min_values'][feature], value)
            xgboost_model['max_values'][feature] = max(xgboost_model['max_values'][feature], value)
    
    # تحديث أوزان الميزات (تعزيز الميزات المرتبطة بالنجاح)
    learning_rate = 0.1
    for feature in features:
        if was_successful:
            xgboost_model['feature_weights'][feature] = xgboost_model['feature_weights'].get(feature, 1.0) * (1 + learning_rate)
        else:
            xgboost_model['feature_weights'][feature] = xgboost_model['feature_weights'].get(feature, 1.0) * (1 - learning_rate)
        # الحفاظ على الوزن ضمن حدود معقولة
        xgboost_model['feature_weights'][feature] = max(0.1, min(5.0, xgboost_model['feature_weights'][feature]))

def save_ai_model():
    """حفظ نموذج AI إلى ملف"""
    global xgboost_model
    if xgboost_model and xgboost_model['trades_count'] >= MIN_TRADES_FOR_AI:
        try:
            with open(AI_MODEL_FILE, 'wb') as f:
                pickle.dump(xgboost_model, f)
            print(f"✅ تم حفظ نموذج AI ({xgboost_model['trades_count']} صفقة)")
        except Exception as e:
            print(f"⚠️ فشل حفظ نموذج AI: {e}")

# =========================================================
# ⭐ نظام كيلي للمخاطرة
# =========================================================
def calculate_kelly_position_size(cash, win_rate, avg_win_pct, avg_loss_pct, base_risk=0.04):
    """حساب حجم الصفقة باستخدام معيار كيلي"""
    
    if win_rate <= 0 or avg_win_pct <= 0 or avg_loss_pct <= 0:
        return cash * base_risk
    
    # تحويل النسب إلى قيم عشرية
    win_rate_decimal = win_rate / 100.0
    avg_win_decimal = avg_win_pct / 100.0
    avg_loss_decimal = abs(avg_loss_pct) / 100.0
    
    # حساب نسبة كيلي
    b = avg_win_decimal / avg_loss_decimal  # نسبة الربح إلى الخسارة
    p = win_rate_decimal
    q = 1 - p
    
    kelly_fraction = (p * b - q) / b
    
    # تطبيق حدود الأمان
    kelly_fraction = max(0, min(kelly_fraction, 0.25))  # حد أقصى 25%
    kelly_fraction = kelly_fraction * KELLY_FRACTION  # استخدام نصف كيلي
    
    # إذا كانت النسبة سالبة أو صفر، استخدم المخاطرة الأساسية
    if kelly_fraction <= 0.01:
        return cash * base_risk
    
    return cash * kelly_fraction

# =========================================================
# ⭐ نظام تنبيهات الانحرافات
# =========================================================
def check_anomalies(trader):
    """فحص وجود انحرافات في الأداء"""
    global is_paused, auto_paused_reason
    
    if len(trader.closed_trades) < 5:
        return False, None
    
    # 1. فحص الخسائر المتتالية
    recent_trades = trader.closed_trades[-MAX_CONSECUTIVE_LOSSES:]
    consecutive_losses = all(t['pnl'] <= 0 for t in recent_trades)
    
    if consecutive_losses:
        return True, f"{MAX_CONSECUTIVE_LOSSES} صفقات خاسرة متتالية"
    
    # 2. فحص التراجع الكبير
    if trader.initial_capital > 0:
        drawdown = (trader.initial_capital - trader.cash) / trader.initial_capital
        if drawdown > MAX_DRAWDOWN_PCT:
            return True, f"تراجع {drawdown*100:.1f}% من رأس المال"
    
    # 3. فحص انخفاض نسبة النجاح (آخر 20 صفقة)
    if len(trader.closed_trades) >= 20:
        last_20 = trader.closed_trades[-20:]
        wins = sum(1 for t in last_20 if t['pnl'] > 0)
        win_rate = wins / 20
        if win_rate < 0.35:  # أقل من 35%
            return True, f"نسبة نجاح منخفضة ({win_rate*100:.0f}%) في آخر 20 صفقة"
    
    return False, None

# =========================================================
# نسخ احتياطي
# =========================================================
def backup_files():
    backup_dir = "backups"
    os.makedirs(backup_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    files_to_backup = ["closed_trades.csv", "hourly_report.csv", "scan_candidates.csv", "paper_trader_state.json", AI_MODEL_FILE]
    
    for file in files_to_backup:
        if os.path.exists(file):
            backup_name = f"{backup_dir}/{date_str}_{file}"
            shutil.copy(file, backup_name)
    
    cleanup_old_backups(backup_dir, days_to_keep=7)
    print(f"✅ تم عمل نسخ احتياطي في {backup_dir}")

def cleanup_old_backups(backup_dir, days_to_keep=7):
    now = datetime.now()
    for filename in os.listdir(backup_dir):
        filepath = os.path.join(backup_dir, filename)
        if os.path.isfile(filepath):
            file_time = datetime.fromtimestamp(os.path.getmtime(filepath))
            if (now - file_time).days > days_to_keep:
                os.remove(filepath)

# =========================================================
# آلية إعادة المحاولة
# =========================================================
async def fetch_with_retry(func, *args, max_retries=3, delay=2, **kwargs):
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            print(f"⚠️ محاولة {attempt+1} فشلت: {e}. إعادة المحاولة بعد {delay} ثانية...")
            await asyncio.sleep(delay)
    return None

# =========================================================
# المؤشرات الفنية (كما هي دون تغيير)
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

def check_volume_confirmation(df):
    if df.empty or len(df) < 20:
        return False, 0
    last_3_volume = df['volume'].iloc[-3:].sum()
    avg_volume_20 = df['volume'].rolling(20).mean().iloc[-1]
    ratio = last_3_volume / avg_volume_20 if avg_volume_20 > 0 else 0
    return ratio > 2.0, ratio

def check_trend_confirmation(df):
    if df.empty or len(df) < 21:
        return False, 0
    ema21 = manual_ema(df['close'], length=21)
    current_price = df['close'].iloc[-1]
    ratio = current_price / ema21.iloc[-1] if ema21.iloc[-1] > 0 else 0
    return current_price > ema21.iloc[-1], ratio

def check_explosion_criteria(candidate):
    score = 0
    details = {}
    details['filter_score'] = candidate.get('filter_score', 0) >= 75
    details['alpha'] = candidate.get('alpha', 0) >= 1.8
    details['target'] = candidate.get('target_pct', 0) >= 18
    eta_bars = candidate.get('eta_bars', 999)
    details['eta'] = eta_bars and eta_bars <= 48
    details['strategy'] = candidate.get('strategy_points', 0) >= 7
    
    score = sum(details.values())
    return score >= 5, score, details

def check_momentum_confirmation(tracker, min_appearances=3):
    confirmed = []
    for symbol, count in tracker.appearance_count.items():
        if count >= min_appearances:
            for cand in tracker.active_candidates:
                if cand['symbol'] == symbol and cand['status'] == 'ACTIVE':
                    confirmed.append(cand)
                    break
    return confirmed

def evaluate_candidate_result(entry_price, current_price):
    if entry_price <= 0:
        return "UNKNOWN", 0
    change_pct = (current_price - entry_price) / entry_price
    if change_pct <= FAIL_THRESHOLD:
        return "FAIL", change_pct
    elif change_pct >= SUCCESS_THRESHOLD:
        return "SUCCESS", change_pct
    elif change_pct >= BREAKEVEN_THRESHOLD:
        return "BREAKEVEN", change_pct
    else:
        return "PENDING", change_pct

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

async def fetch_ticker_fast(exchange, symbol):
    try:
        ticker = await fetch_with_retry(exchange.fetch_ticker, symbol)
        if not ticker:
            return None
        bid = ticker.get('bid', 0) or 0
        ask = ticker.get('ask', 0) or 0
        bid_volume = ticker.get('bidVolume', 0) or 0
        ask_volume = ticker.get('askVolume', 0) or 0
        obi = (bid_volume - ask_volume) / (bid_volume + ask_volume) if (bid_volume + ask_volume) > 0 else 0
        change_24h = ticker.get('percentage', 0) or 0
        return {
            'symbol': symbol,
            'volume_24h': ticker.get('quoteVolume', 0) or 0,
            'high': ticker.get('high', 0) or 0,
            'low': ticker.get('low', 0) or 0,
            'close': ticker.get('close', 0) or 0,
            'bid': bid,
            'ask': ask,
            'obi': obi,
            'change_24h': change_24h
        }
    except:
        return None

async def batched_lightning_scan(exchange, symbols_to_scan, min_volume=500000, min_volatility=0.015):
    print(f"⚡ بدء المسح المقسم لـ {len(symbols_to_scan)} عملة...")
    
    passed = []
    total_batches = (len(symbols_to_scan) + BATCH_SIZE - 1) // BATCH_SIZE
    
    for batch_num in range(total_batches):
        start_idx = batch_num * BATCH_SIZE
        end_idx = min(start_idx + BATCH_SIZE, len(symbols_to_scan))
        batch_symbols = symbols_to_scan[start_idx:end_idx]
        
        tasks = [fetch_ticker_fast(exchange, sym) for sym in batch_symbols]
        results = await asyncio.gather(*tasks)
        
        for r in results:
            if r is None or r['close'] <= 0:
                continue
            volatility = (r['high'] - r['low']) / r['close'] if r['close'] > 0 else 0
            if r['change_24h'] > 50:
                continue
            if r['volume_24h'] >= min_volume and volatility >= min_volatility:
                r['volatility'] = volatility
                passed.append(r)
        
        print(f"   ✅ دفعة {batch_num+1}/{total_batches} اكتملت ({len(passed)} عملة ناجحة حتى الآن)")
        
        if batch_num < total_batches - 1:
            await asyncio.sleep(BATCH_DELAY)
    
    print(f"✅ اكتمل المسح: {len(passed)} عملة اجتازت الفلترة السريعة")
    return passed

def calculate_filter_score(df):
    if df.empty or len(df) < 20:
        return 0, {}
    
    details = {}
    last = df.iloc[-1]
    score = 0
    
    avg_vol = df['volume'].rolling(20).mean().iloc[-1]
    if pd.notna(avg_vol) and avg_vol > 0:
        vol_ratio = last['volume'] / avg_vol
        details['volume_ratio'] = vol_ratio
        if vol_ratio > 2.0: score += 15
        if vol_ratio > 3.0: score += 15
        
    rsi_series = manual_rsi(df['close'], length=14)
    if not rsi_series.empty:
        rsi = rsi_series.iloc[-1]
        details['rsi'] = rsi
        if pd.notna(rsi):
            if 50 < rsi < 75: score += 20
            elif rsi > 75: score += 10
            
    upper, _, _ = manual_donchian(df['high'], df['low'], length=20)
    details['donchian_breakout'] = pd.notna(upper.iloc[-1]) and last['close'] > upper.iloc[-1]
    if details['donchian_breakout']:
        score += 20
        
    macd_line, signal_line, _ = manual_macd(df['close'])
    details['macd_bullish'] = pd.notna(macd_line.iloc[-1]) and pd.notna(signal_line.iloc[-1]) and macd_line.iloc[-1] > signal_line.iloc[-1]
    if details['macd_bullish']:
        score += 15
        
    bb_upper, _, _ = manual_bollinger_bands(df['close'])
    details['bb_breakout'] = pd.notna(bb_upper.iloc[-1]) and last['close'] > bb_upper.iloc[-1]
    if details['bb_breakout']:
        score += 15
    
    tsi_series = manual_tsi(df['close'])
    if not tsi_series.empty and pd.notna(tsi_series.iloc[-1]):
        tsi_val = tsi_series.iloc[-1]
        details['tsi'] = tsi_val
        if tsi_val > 0:
            score += 10
        if tsi_val > 10:
            score += 5
            
    return score, details

def check_strategies_weighted(df, obi=0):
    points = 0
    details = {}
    
    if df.empty or len(df) < 20:
        return 0, details
        
    last = df.iloc[-1]
    avg_vol = df['volume'].rolling(20).mean().iloc[-1]
    avg_price = df['close'].rolling(20).mean().iloc[-1]
    
    details['hidden_volume'] = False
    if pd.notna(avg_vol) and pd.notna(avg_price) and avg_price > 0:
        if last['volume'] > avg_vol * 2.5 and abs(last['close'] - avg_price) / avg_price < 0.02:
            points += 3
            details['hidden_volume'] = True
            
    details['whale_activity'] = False
    if pd.notna(avg_vol) and last['volume'] > avg_vol * 4:
        points += 3
        details['whale_activity'] = True
        
    details['true_breakout'] = False
    resistance = df['high'].rolling(20).max().iloc[-2]
    adx_series = manual_adx(df['high'], df['low'], df['close'])
    if not adx_series.empty:
        adx = adx_series.iloc[-1]
        if pd.notna(resistance) and pd.notna(adx) and pd.notna(avg_vol):
            if last['close'] > resistance and last['volume'] > avg_vol and adx > 25:
                points += 2
                details['true_breakout'] = True
                
    details['golden_cross'] = False
    ema9 = manual_ema(df['close'], length=9)
    ema21 = manual_ema(df['close'], length=21)
    if not ema9.empty and not ema21.empty:
        if ema9.iloc[-1] > ema21.iloc[-1] and ema9.iloc[-2] <= ema21.iloc[-2]:
            points += 1
            details['golden_cross'] = True
            
    details['ema_slope_positive'] = False
    ema_slope = get_ema_slope(df['close'], length=20, periods=3)
    if ema_slope > 0.001:
        points += 1
        details['ema_slope_positive'] = True
        
    details['obi_signal'] = obi
    if obi > 0.1:
        points += 1
    elif obi > 0.2:
        points += 2
        
    return points, details

def calculate_enhanced_alpha(df, market_context, obi=0):
    if df.empty or len(df) < 20:
        return 0.0, {}
        
    details = {}
    last = df.iloc[-1]
    avg_vol = df['volume'].rolling(20).mean().iloc[-1]
    vol_ratio = last['volume'] / avg_vol if avg_vol > 0 else 1.0
    details['vol_ratio'] = vol_ratio
    
    atr_series = manual_atr(df['high'], df['low'], df['close'])
    atr = atr_series.iloc[-1] if not atr_series.empty else 0
    details['atr'] = atr
    
    resistance = df['high'].rolling(20).max().iloc[-2]
    breakout_strength = (last['close'] - resistance) / atr if atr > 0 else 0
    details['breakout_strength'] = breakout_strength
    
    tsi_series = manual_tsi(df['close'])
    tsi_val = tsi_series.iloc[-1] if not tsi_series.empty else 0
    details['tsi'] = tsi_val
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
        
    details['weights'] = {'vol': w_vol, 'breakout': w_break, 'depth': w_depth, 'tsi': w_tsi}
    
    raw_alpha = (z_vol * w_vol) + (z_breakout * w_break) + (z_depth * w_depth) + (tsi_signal * w_tsi)
    beta_adj = -0.05 if regime == 'COLD' else (0.03 if regime == 'HOT' else 0.0)
    
    return round(raw_alpha + beta_adj, 4), details

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
# متتبع الترشيحات (مع نظام تسجيل النقاط)
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
                    'Scan Time', 'Symbol', 'Rank', 'Entry Price', 'Stop Loss', 'Take Profit',
                    'Target %', 'Alpha', 'ETA', 'Filter Score', 'Strategy Points',
                    'Volume Ratio', 'RSI', 'Donchian', 'MACD', 'BB', 'TSI',
                    'Hidden Vol', 'Whale', 'Breakout', 'Golden Cross', 'OBI',
                    'Vol Confirm', 'Trend Confirm', 'AI Confidence', 'Status', 
                    'Close Time', 'Final Price', 'Current Change %', 'Evaluation', 'PNL %'
                ])

    def add_candidates(self, candidates_list, scan_time):
        for cand in candidates_list[:TOP_CANDIDATES_COUNT]:
            symbol = cand['symbol']
            self.appearance_count[symbol] = self.appearance_count.get(symbol, 0) + 1
        
        current_symbols = {c['symbol'] for c in candidates_list[:TOP_CANDIDATES_COUNT]}
        for symbol in list(self.appearance_count.keys()):
            if symbol not in current_symbols:
                self.appearance_count[symbol] = 0
        
        for rank, cand in enumerate(candidates_list[:TOP_CANDIDATES_COUNT], 1):
            record = {
                'scan_time': scan_time,
                'symbol': cand['symbol'],
                'rank': rank,
                'entry_price': cand['entry_price'],
                'stop_loss': cand['stop_loss'],
                'take_profit': cand['take_profit'],
                'target_pct': cand['target_pct'],
                'alpha': cand['alpha'],
                'eta_str': cand['eta_str'],
                'filter_score': cand.get('filter_score', 0),
                'strategy_points': cand.get('strategy_points', 0),
                'filter_details': cand.get('filter_details', {}),
                'strategy_details': cand.get('strategy_details', {}),
                'alpha_details': cand.get('alpha_details', {}),
                'volume_confirm': cand.get('volume_confirm', False),
                'trend_confirm': cand.get('trend_confirm', False),
                'ai_confidence': cand.get('ai_confidence', 0.5),
                'status': 'ACTIVE',
                'close_time': None,
                'final_price': None,
                'current_change_pct': 0,
                'evaluation': 'PENDING',
                'pnl_pct': None
            }
            self.active_candidates.append(record)
            self._write_record(record)

    def _write_record(self, record):
        with open(self.candidates_csv, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            fd = record.get('filter_details', {})
            sd = record.get('strategy_details', {})
            
            writer.writerow([
                record['scan_time'].isoformat(),
                record['symbol'],
                record['rank'],
                f"{record['entry_price']:.4f}",
                f"{record['stop_loss']:.4f}",
                f"{record['take_profit']:.4f}",
                f"{record['target_pct']:.2f}",
                f"{record['alpha']:.3f}",
                record['eta_str'],
                record['filter_score'],
                record['strategy_points'],
                f"{fd.get('volume_ratio', 0):.2f}",
                f"{fd.get('rsi', 0):.1f}",
                str(fd.get('donchian_breakout', False)),
                str(fd.get('macd_bullish', False)),
                str(fd.get('bb_breakout', False)),
                f"{fd.get('tsi', 0):.1f}",
                str(sd.get('hidden_volume', False)),
                str(sd.get('whale_activity', False)),
                str(sd.get('true_breakout', False)),
                str(sd.get('golden_cross', False)),
                f"{sd.get('obi_signal', 0):.2f}",
                str(record.get('volume_confirm', False)),
                str(record.get('trend_confirm', False)),
                f"{record.get('ai_confidence', 0.5):.3f}",
                record['status'],
                record['close_time'].isoformat() if record['close_time'] else '',
                f"{record['final_price']:.4f}" if record['final_price'] else '',
                f"{record['current_change_pct']:.2f}%" if record['current_change_pct'] else '',
                record['evaluation'],
                f"{record['pnl_pct']:.2f}" if record['pnl_pct'] is not None else ''
            ])

    def update_candidates(self, current_prices, max_age_hours=24):
        now = datetime.now()
        for cand in self.active_candidates:
            if cand['status'] not in ['ACTIVE', 'PENDING']:
                continue
            symbol = cand['symbol']
            if symbol not in current_prices:
                continue
            price = current_prices[symbol]
            change_pct = ((price - cand['entry_price']) / cand['entry_price']) * 100
            cand['current_change_pct'] = change_pct
            evaluation, eval_pct = evaluate_candidate_result(cand['entry_price'], price)
            cand['evaluation'] = evaluation
            age = (now - cand['scan_time']).total_seconds() / 3600
            
            if evaluation == "FAIL":
                cand['status'] = 'CLOSED'
                cand['close_time'] = now
                cand['final_price'] = price
                cand['result'] = 'FAIL'
                cand['pnl_pct'] = change_pct
                self._write_record(cand)
            elif evaluation == "SUCCESS":
                cand['status'] = 'CLOSED'
                cand['close_time'] = now
                cand['final_price'] = price
                cand['result'] = 'SUCCESS'
                cand['pnl_pct'] = change_pct
                self._write_record(cand)
            elif evaluation == "BREAKEVEN":
                cand['status'] = 'CLOSED'
                cand['close_time'] = now
                cand['final_price'] = price
                cand['result'] = 'BREAKEVEN'
                cand['pnl_pct'] = change_pct
                self._write_record(cand)
            elif age > max_age_hours:
                cand['status'] = 'EXPIRED'
                cand['close_time'] = now
                cand['final_price'] = price
                cand['result'] = 'EXPIRED'
                cand['pnl_pct'] = change_pct
                cand['evaluation'] = 'EXPIRED'
                self._write_record(cand)
            elif price <= cand['stop_loss']:
                cand['status'] = 'CLOSED'
                cand['close_time'] = now
                cand['final_price'] = price
                cand['result'] = 'STOP_LOSS'
                cand['pnl_pct'] = change_pct
                cand['evaluation'] = 'STOP_LOSS'
                self._write_record(cand)
            elif price >= cand['take_profit']:
                cand['status'] = 'CLOSED'
                cand['close_time'] = now
                cand['final_price'] = price
                cand['result'] = 'TAKE_PROFIT'
                cand['pnl_pct'] = change_pct
                cand['evaluation'] = 'TAKE_PROFIT'
                self._write_record(cand)
            else:
                self._write_record(cand)
                
        self.active_candidates = [c for c in self.active_candidates if c['status'] == 'ACTIVE']

# =========================================================
# نظام التداول الورقي (مع كيلي و AI)
# =========================================================
class PaperTrader:
    def __init__(self, initial_capital=1000, max_positions=float('inf')):
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
                                 'Signal Type', 'AI Confidence', 'Kelly Fraction'])
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
                f"{trade.get('ai_confidence', 0.5):.3f}",
                f"{trade.get('kelly_fraction', 0.04):.3f}"
            ])

    def get_kelly_stats(self):
        """حساب إحصائيات كيلي من الصفقات المغلقة"""
        if len(self.closed_trades) < MIN_TRADES_FOR_KELLY:
            return None, None, None
        
        wins = [t for t in self.closed_trades if t['pnl'] > 0]
        losses = [t for t in self.closed_trades if t['pnl'] <= 0]
        
        if not wins or not losses:
            return None, None, None
        
        win_rate = len(wins) / len(self.closed_trades) * 100
        avg_win = sum(t['pnl_pct'] for t in wins) / len(wins)
        avg_loss = abs(sum(t['pnl_pct'] for t in losses) / len(losses))
        
        return win_rate, avg_win, avg_loss

    def open_position(self, signal, exchange, signal_type='alpha', is_late_entry=False, ai_confidence=0.5):
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
        
        # فلتر التقلب الحاد
        volatility_pct = atr / entry_price
        if volatility_pct > 0.10:
            print(f"⚠️ تقلب عالي جداً ({volatility_pct*100:.1f}%)، تم تخطي {symbol}")
            return False
        
        atr_multiplier = 2.0 if is_late_entry else 3.0
        stop_loss = entry_price - (atr_multiplier * atr)
        take_profit = entry_price * (1 + target_pct / 100)
        
        # ⭐ حساب حجم الصفقة (مع كيلي إذا توفرت البيانات)
        win_rate, avg_win, avg_loss = self.get_kelly_stats()
        if win_rate and avg_win and avg_loss:
            base_risk = 0.04
            kelly_amount = calculate_kelly_position_size(self.cash, win_rate, avg_win, avg_loss, base_risk)
            position_value = kelly_amount
        else:
            position_value = calculate_dynamic_position_size(
                signal_type, self.cash, entry_price, stop_loss, target_pct, alpha, is_late_entry
            )
        
        # ⭐ تعديل حجم الصفقة بناءً على ثقة AI
        if ai_confidence > 0.5:
            position_value *= (1 + (ai_confidence - 0.5))
        elif ai_confidence < 0.4:
            position_value *= ai_confidence * 2
        
        position_value = min(position_value, self.cash * 0.95)
        position_value = max(position_value, 50)  # حد أدنى 50$
        
        if position_value <= 0 or position_value > self.cash:
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

        if position_value > self.cash:
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
            'ai_confidence': ai_confidence,
            'features': signal.get('features', {})
        }
        self.positions.append(position)

        kelly_tag = " (كيلي)" if win_rate else ""
        late_tag = " (دخول متأخر)" if is_late_entry else ""
        msg = (f"🟢 صفقة جديدة ({signal_type}{late_tag}{kelly_tag}): {symbol}\n"
               f"سعر الدخول: {entry_price:.4f}\n"
               f"قيمة الصفقة: {position_value:.2f}$\n"
               f"كمية: {amount:.4f}\n"
               f"🛑 وقف الخسارة: {stop_loss:.4f}\n"
               f"🎯 جني الأرباح: {take_profit:.4f}\n"
               f"📈 نسبة الصعود: {target_pct:.2f}%\n"
               f"⏱️ الوقت المتوقع: {eta_str}\n"
               f"⭐ سكور ألفا: {alpha:.3f}\n"
               f"🤖 ثقة AI: {ai_confidence*100:.0f}%\n"
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
        
        # ⭐ تحديث نموذج AI بنتيجة الصفقة
        if 'features' in pos:
            was_successful = pnl > 0
            update_ai_model(pos['features'], was_successful)
        
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
            'ai_confidence': pos.get('ai_confidence', 0.5),
            'kelly_fraction': 0.04
        }
        self.closed_trades.append(trade_record)
        self._append_trade_to_csv(trade_record)
        
        msg = f"🔴 إغلاق {pos['symbol']}: {reason} | ربح = {pnl:.2f}$ ({pnl_pct:.2f}%) | الرصيد = {self.cash:.2f}$"
        print(msg)
        asyncio.create_task(send_telegram_message(msg))
        self.save_state()
        
        # حفظ نموذج AI كل 10 صفقات
        if len(self.closed_trades) % 10 == 0:
            save_ai_model()

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
# أوامر الإيقاف المؤقت الذكي
# =========================================================
async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_paused, pause_until_time, auto_paused_reason
    is_paused = True
    pause_until_time = None
    auto_paused_reason = "يدوي"
    await update.message.reply_text("⏸️ تم إيقاف فتح الصفقات الجديدة مؤقتاً.\nاستخدم /resume للاستئناف.")

async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_paused, pause_until_time, auto_paused_reason
    is_paused = False
    pause_until_time = None
    auto_paused_reason = None
    await update.message.reply_text("▶️ تم استئناف فتح الصفقات الجديدة.")

async def pause_until_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_paused, pause_until_time, auto_paused_reason
    try:
        time_str = context.args[0] if context.args else "23:59"
        hour, minute = map(int, time_str.split(':'))
        now = datetime.now()
        pause_until_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if pause_until_time <= now:
            pause_until_time += timedelta(days=1)
        is_paused = True
        auto_paused_reason = "يدوي (مؤقت)"
        await update.message.reply_text(f"⏸️ تم إيقاف فتح الصفقات حتى الساعة {time_str}")
    except:
        await update.message.reply_text("❌ صيغة غير صحيحة. استخدم: /pause_until 22:30")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_paused, pause_until_time, auto_paused_reason, trader_instance
    
    if trader_instance is None:
        await update.message.reply_text("⚠️ نظام التداول غير مهيأ بعد.")
        return
        
    status_text = "🟢 نشط" if not is_paused else "⏸️ متوقف مؤقتاً"
    if auto_paused_reason:
        status_text += f" ({auto_paused_reason})"
    if pause_until_time:
        status_text += f" حتى {pause_until_time.strftime('%H:%M')}"
    
    stats = trader_instance.get_stats()
    ai_trades = xgboost_model['trades_count'] if xgboost_model else 0
    
    if stats:
        msg = f"🤖 حالة البوت: {status_text}\n"
        msg += f"💰 الرصيد: {trader_instance.cash:.2f}$\n"
        msg += f"📈 العائد: {stats['total_pnl']:.2f}$ ({stats['total_return_pct']:.2f}%)\n"
        msg += f"📋 صفقات: {stats['total_trades']} | ✅ {stats['win_count']} | ❌ {stats['loss_count']}\n"
        msg += f"🎯 نسبة النجاح: {stats['win_rate']:.2f}%\n"
        msg += f"🔓 صفقات مفتوحة: {stats['open_positions']}\n"
        msg += f"🧠 صفقات AI: {ai_trades}"
    else:
        msg = f"🤖 حالة البوت: {status_text}\n💰 الرصيد: {trader_instance.cash:.2f}$"
    
    await update.message.reply_text(msg)

# =========================================================
# حلقة التداول الرئيسية
# =========================================================
async def trading_loop():
    global exchange_sync_instance, candidate_tracker, current_cycle, all_symbols
    global is_paused, pause_until_time, auto_paused_reason, trader_instance

    exchange_async = ccxt_async.gateio({'enableRateLimit': True})
    exchange_sync = ccxt.gateio({'enableRateLimit': True})
    exchange_sync_instance = exchange_sync

    markets = await fetch_with_retry(exchange_async.load_markets)
    if markets:
        all_symbols = [s for s in markets if s.endswith('/USDT') and '.d' not in s]
        print(f"📋 تم تحميل {len(all_symbols)} عملة كاملة")
    else:
        print("❌ فشل تحميل قائمة العملات")
        return

    trader = PaperTrader(initial_capital=INITIAL_CAPITAL)
    trader_instance = trader
    tracker = CandidateTracker()
    candidate_tracker = tracker
    
    # ⭐ تهيئة نموذج AI
    init_ai_model()

    reject_reasons = {
        "volume_spike": 0, "filter_score": 0, "strategy": 0,
        "cold_market": 0, "insufficient_cash": 0, "high_change_24h": 0,
        "volume_confirm": 0, "trend_confirm": 0, "high_volatility": 0,
        "ai_rejected": 0
    }

    last_report = time.time()
    last_candidates_sent = time.time()
    last_backup = time.time()
    last_ai_save = time.time()
    
    print(f"🤖 بدء التداول الورقي (مع AI + كيلي + انحرافات) - {datetime.now()}\n")
    await asyncio.sleep(2)
    await send_telegram_message(f"🚀 بوت التداول الورقي المتقدم بدأ العمل!\n📊 مسح {SYMBOLS_PER_CYCLE} عملة كل 30 دقيقة\n🧠 AI: {'مفعل' if AI_ENABLED else 'معطل'}\n📈 كيلي: {'مفعل' if trader.closed_trades else 'ينتظر البيانات'}")

    while True:
        try:
            # ⭐ فحص الانحرافات قبل كل دورة
            if not is_paused:
                has_anomaly, anomaly_reason = check_anomalies(trader)
                if has_anomaly:
                    is_paused = True
                    auto_paused_reason = f"تلقائي: {anomaly_reason}"
                    await send_telegram_message(f"🚨🚨🚨 تنبيه انحراف 🚨🚨🚨\n\nتم إيقاف البوت تلقائياً بسبب:\n{anomaly_reason}\n\nاستخدم /resume للاستئناف بعد المراجعة.")
                    await asyncio.sleep(60)
                    continue
            
            # فحص الإيقاف المؤقت
            if is_paused:
                if pause_until_time and datetime.now() >= pause_until_time:
                    is_paused = False
                    pause_until_time = None
                    auto_paused_reason = None
                    await send_telegram_message("▶️ تم استئناف التداول تلقائياً حسب الوقت المحدد.")
                else:
                    await asyncio.sleep(60)
                    continue
            
            # تحديد مجموعة العملات لهذه الدورة
            total_symbols = len(all_symbols)
            if current_cycle == 1:
                symbols_to_scan = all_symbols[:SYMBOLS_PER_CYCLE]
                print(f"\n🔄 الدورة 1: مسح أول {len(symbols_to_scan)} عملة")
                current_cycle = 2
            else:
                start_idx = SYMBOLS_PER_CYCLE
                end_idx = min(start_idx + SYMBOLS_PER_CYCLE, total_symbols)
                symbols_to_scan = all_symbols[start_idx:end_idx]
                print(f"\n🔄 الدورة 2: مسح {len(symbols_to_scan)} عملة (من {start_idx} إلى {end_idx})")
                current_cycle = 1

            results = await batched_lightning_scan(exchange_async, symbols_to_scan)
            
            if not results:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            market_ctx = detect_market_regime(exchange_sync)

            if market_ctx.get('regime') == 'COLD':
                print("⚠️ السوق بارد (COLD)، تم تخطي فتح الصفقات")
                reject_reasons["cold_market"] += 1
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            candidates = []
            for item in results:
                if item.get('change_24h', 0) > 50:
                    reject_reasons["high_change_24h"] += 1
                    continue

                df = fetch_ohlcv_sync(exchange_sync, item['symbol'], '5m', 40)
                if df.empty:
                    continue

                last_volume = df['volume'].iloc[-1]
                avg_volume_20 = df['volume'].rolling(20).mean().iloc[-1]
                if pd.isna(avg_volume_20) or last_volume < avg_volume_20 * 1.5:
                    reject_reasons["volume_spike"] += 1
                    continue

                fs, filter_details = calculate_filter_score(df)
                if fs < 20:
                    reject_reasons["filter_score"] += 1
                    continue

                obi = item.get('obi', 0)
                sp, strategy_details = check_strategies_weighted(df, obi)
                if sp < 2:
                    reject_reasons["strategy"] += 1
                    continue

                vol_confirm, vol_ratio = check_volume_confirmation(df)
                if not vol_confirm:
                    reject_reasons["volume_confirm"] += 1
                    continue

                trend_confirm, trend_ratio = check_trend_confirmation(df)
                if not trend_confirm:
                    reject_reasons["trend_confirm"] += 1
                    continue

                alpha, alpha_details = calculate_enhanced_alpha(df, market_ctx, obi)
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
                    'filter_details': filter_details,
                    'strategy_details': strategy_details,
                    'alpha_details': alpha_details,
                    'volume_confirm': vol_confirm,
                    'trend_confirm': trend_confirm,
                    'volatility_pct': 0
                }
                
                # حساب التقلب
                if df is not None and len(df) > 14:
                    atr_series = manual_atr(df['high'], df['low'], df['close'])
                    atr = atr_series.iloc[-1] if not atr_series.empty else last_price * 0.03
                    cand['volatility_pct'] = atr / last_price
                
                # ⭐ حساب ثقة AI
                if AI_ENABLED:
                    features = prepare_ai_features(cand, market_ctx)
                    cand['features'] = features
                    cand['ai_confidence'] = predict_confidence(features)
                else:
                    cand['ai_confidence'] = 0.5
                
                candidates.append(cand)

            if not candidates:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            candidates.sort(key=lambda x: x['final_rank'], reverse=True)

            # أولوية 1: فحص الانفجار الوشيك
            for cand in candidates[:TOP_CANDIDATES_COUNT]:
                is_explosive, criteria_met, details = check_explosion_criteria(cand)
                if is_explosive:
                    msg = f"🔥🔥🔥 تنبيه انفجار وشيك 🔥🔥🔥\n\n"
                    msg += f"{cand['symbol']}\n"
                    msg += f"سعر الدخول: {cand['entry_price']:.4f}\n"
                    msg += f"سكور ألفا: {cand['alpha']:.3f}\n"
                    msg += f"نسبة الصعود: {cand['target_pct']:.2f}%\n"
                    msg += f"الوقت المتوقع: {cand['eta_str']}\n"
                    msg += f"نقاط الاستراتيجية: {cand['strategy_points']}/10\n"
                    msg += f"سكور الفلتر: {cand['filter_score']}/100\n"
                    msg += f"🤖 ثقة AI: {cand['ai_confidence']*100:.0f}%\n"
                    msg += f"\n⚠️ هذه العملة تحقق {criteria_met}/5 من معايير الانفجار القوي"
                    asyncio.create_task(send_telegram_message(msg))
                    
                    already_open = any(p['symbol'] == cand['symbol'] for p in trader.positions)
                    if not already_open and trader.cash > 50:
                        df = cand['df']
                        if df is not None and len(df) > 14:
                            atr_series = manual_atr(df['high'], df['low'], df['close'])
                            atr = atr_series.iloc[-1] if not atr_series.empty else cand['entry_price'] * 0.03
                        else:
                            atr = cand['entry_price'] * 0.03
                        cand['stop_loss'] = cand['entry_price'] - (3.0 * atr)
                        cand['take_profit'] = cand['entry_price'] * (1 + cand['target_pct'] / 100)
                        
                        # ⭐ فحص ثقة AI قبل الفتح
                        if cand['ai_confidence'] >= AI_CONFIDENCE_THRESHOLD:
                            trader.open_position(cand, exchange_sync, signal_type='explosion', is_late_entry=False, ai_confidence=cand['ai_confidence'])
                        else:
                            reject_reasons["ai_rejected"] += 1
                            print(f"⚠️ تم رفض {cand['symbol']} بسبب انخفاض ثقة AI ({cand['ai_confidence']*100:.0f}%)")

            # تحضير للتأكيد متعدد الدورات
            for cand in candidates[:TOP_CANDIDATES_COUNT]:
                df = cand['df']
                if df is not None and len(df) > 14:
                    atr_series = manual_atr(df['high'], df['low'], df['close'])
                    atr = atr_series.iloc[-1] if not atr_series.empty else cand['entry_price'] * 0.03
                else:
                    atr = cand['entry_price'] * 0.03
                cand['stop_loss'] = cand['entry_price'] - (3.0 * atr)
                cand['take_profit'] = cand['entry_price'] * (1 + cand['target_pct'] / 100)

            tracker.add_candidates(candidates[:TOP_CANDIDATES_COUNT], datetime.now())
            
            confirmed_momentum = check_momentum_confirmation(tracker, MIN_APPEARANCES)
            for cand in confirmed_momentum:
                msg = f"🚀🚀🚀 تأكيد زخم متعدد الدورات 🚀🚀🚀\n\n"
                msg += f"{cand['symbol']} ظهرت في أفضل {TOP_CANDIDATES_COUNT} ترشيحات لـ {MIN_APPEARANCES} دورات متتالية!\n"
                msg += f"سعر الدخول: {cand['entry_price']:.4f}\n"
                msg += f"نسبة الصعود: {cand['target_pct']:.2f}%\n"
                msg += f"سكور ألفا: {cand['alpha']:.3f}\n"
                msg += f"🤖 ثقة AI: {cand['ai_confidence']*100:.0f}%"
                asyncio.create_task(send_telegram_message(msg))
                
                already_open = any(p['symbol'] == cand['symbol'] for p in trader.positions)
                if not already_open and trader.cash > 50:
                    appearance_count = tracker.appearance_count.get(cand['symbol'], 0)
                    is_late = appearance_count > 3
                    
                    if cand['ai_confidence'] >= AI_CONFIDENCE_THRESHOLD:
                        trader.open_position(cand, exchange_sync, signal_type='momentum', is_late_entry=is_late, ai_confidence=cand['ai_confidence'])
                    else:
                        reject_reasons["ai_rejected"] += 1

            # أولوية 3: أفضل مرشح
            best = candidates[0]
            print(f"\n🏆 أفضل مرشح: {best['symbol']} | سعر {best['entry_price']:.4f} | ألفا {best['alpha']:.3f} | هدف {best['target_pct']:.2f}% | AI: {best['ai_confidence']*100:.0f}%")
            
            if best['alpha'] >= 2.0 and best['target_pct'] >= 15:
                already_open = any(p['symbol'] == best['symbol'] for p in trader.positions)
                if not already_open and trader.cash > 50:
                    if best['ai_confidence'] >= AI_CONFIDENCE_THRESHOLD:
                        trader.open_position(best, exchange_sync, signal_type='alpha', is_late_entry=False, ai_confidence=best['ai_confidence'])
                    else:
                        reject_reasons["ai_rejected"] += 1

            # إرسال قائمة الترشيحات
            if time.time() - last_candidates_sent >= 1080:
                msg = f"📋 أفضل {TOP_CANDIDATES_COUNT} ترشيحات حالياً:\n\n"
                for i, c in enumerate(candidates[:TOP_CANDIDATES_COUNT], 1):
                    msg += f"{i}. {c['symbol']} | سعر: {c['entry_price']:.4f} | ألفا: {c['alpha']:.3f} | هدف: {c['target_pct']:.2f}% | AI: {c['ai_confidence']*100:.0f}%\n"
                asyncio.create_task(send_telegram_message(msg))
                last_candidates_sent = time.time()

            # تحديث الأسعار
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

            for cand in candidates[:TOP_CANDIDATES_COUNT]:
                sym = cand['symbol']
                if sym not in prices:
                    try:
                        ticker = await fetch_with_retry(exchange_sync.fetch_ticker, sym)
                        if ticker:
                            prices[sym] = ticker['last']
                    except:
                        pass
            tracker.update_candidates(prices)

            # تقرير كل ساعة
            if time.time() - last_report >= 3600:
                report = trader.generate_report(prices)
                if report:
                    reject_msg = f"\n📊 أسباب الرفض: حجم شمعة={reject_reasons['volume_spike']}, سكور={reject_reasons['filter_score']}, استراتيجية={reject_reasons['strategy']}, سوق بارد={reject_reasons['cold_market']}, ارتفاع >50%={reject_reasons['high_change_24h']}, حجم تراكمي={reject_reasons['volume_confirm']}, اتجاه={reject_reasons['trend_confirm']}, تقلب حاد={reject_reasons['high_volatility']}, AI رفض={reject_reasons['ai_rejected']}"
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
                last_report = time.time()

            # نسخ احتياطي كل 24 ساعة
            if time.time() - last_backup >= 86400:
                backup_files()
                last_backup = time.time()
            
            # حفظ نموذج AI كل ساعة
            if time.time() - last_ai_save >= 3600:
                save_ai_model()
                last_ai_save = time.time()

            await asyncio.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            print("\n👋 إيقاف...")
            save_ai_model()
            await send_telegram_message("⏹️ تم إيقاف البوت.")
            break
        except Exception as e:
            print(f"❌ خطأ: {e}")
            await asyncio.sleep(60)

    await exchange_async.close()

# =========================================================
# بوت تيليجرام
# =========================================================
async def run_telegram_bot():
    global telegram_app
    telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    telegram_app.add_handler(CommandHandler("status", status_command))
    telegram_app.add_handler(CommandHandler("pause", pause_command))
    telegram_app.add_handler(CommandHandler("resume", resume_command))
    telegram_app.add_handler(CommandHandler("pause_until", pause_until_command))
    
    print("🤖 بوت Telegram قيد التشغيل...")
    await telegram_app.run_polling()

async def main():
    global telegram_app
    telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()
    await telegram_app.initialize()
    print("🤖 تطبيق Telegram جاهز للإرسال...")
    
    await asyncio.gather(
        run_telegram_bot(),
        trading_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())
