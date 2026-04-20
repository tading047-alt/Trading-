"""
نظام التداول الورقي المتكامل - الإصدار النهائي
=============================================
الميزات الكاملة:
- مسح مقسم على دفعات (100 عملة/دفعة، 500 عملة/دورة)
- تتبع سعر العملات المرشحة كل دقيقة
- تقييم افتراضي: نجاح (+6%) / فشل (-3%)
- شروط انفجار وشيك مخففة (4/5 بدلاً من 5/5)
- شروط عملة جيدة للدخول الاحتياطي
- نظام كيلي للمخاطرة
- تنبيهات الانحرافات
- نسخ احتياطي تلقائي
- إيقاف مؤقت ذكي
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
# إعدادات التداول (مخففة)
# =========================================================
INITIAL_CAPITAL = 1000
MAX_POSITIONS = float('inf')
MIN_APPEARANCES = 2
TOP_CANDIDATES_COUNT = 5

# إعدادات المسح
BATCH_SIZE = 100
BATCH_DELAY = 2.5
SYMBOLS_PER_CYCLE = 500
SCAN_INTERVAL = 1800
PRICE_UPDATE_INTERVAL = 60

# عتبات تقييم النتائج
FAIL_THRESHOLD = -0.03
SUCCESS_THRESHOLD = 0.06
MAX_AGE_HOURS = 24

# إعدادات كيلي
KELLY_FRACTION = 0.5
MIN_TRADES_FOR_KELLY = 10

# إعدادات الانحرافات
MAX_CONSECUTIVE_LOSSES = 5
MAX_DRAWDOWN_PCT = 0.25

# متغيرات الإيقاف
is_paused = False
pause_until_time = None
auto_paused_reason = None

# متغيرات المسح
current_cycle = 1
all_symbols = []

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
    print(f"✅ تم عمل نسخ احتياطي في {backup_dir}")

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
    return 100 - (100 / (1 + rs))

def manual_macd(close, fast=12, slow=26, signal=9):
    ema_fast = manual_ema(close, fast)
    ema_slow = manual_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = manual_ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line

def manual_atr(high, low, close, length=14):
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()

def manual_donchian(high, low, length=20):
    upper = high.rolling(window=length).max()
    lower = low.rolling(window=length).min()
    return upper, lower, (upper + lower) / 2

def manual_bollinger_bands(close, length=20, std=2):
    middle = close.rolling(window=length).mean()
    std_dev = close.rolling(window=length).std()
    return middle + (std_dev * std), middle, middle - (std_dev * std)

def manual_tsi(close, r=25, s=13):
    momentum = close.diff(1)
    ema_mom = manual_ema(momentum, r)
    ema_abs = manual_ema(abs(momentum), r)
    return 100 * (manual_ema(ema_mom, s) / manual_ema(ema_abs, s))

def get_ema_slope(close, length=20, periods=3):
    ema = manual_ema(close, length)
    if len(ema) < periods:
        return 0
    return (ema.iloc[-1] - ema.iloc[-periods]) / periods

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
    return dx.rolling(window=length).mean()

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
# ⭐ شروط الانفجار الوشيك (مخففة)
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
# ⭐ شروط العملة الجيدة
# =========================================================
def check_good_coin_criteria(candidate):
    criteria_met = []
    missing = []
    
    if candidate.get('filter_score', 0) >= 35:
        criteria_met.append("سكور فلتر ≥ 35")
    else:
        missing.append(f"سكور فلتر ({candidate.get('filter_score', 0)})")
    
    if candidate.get('alpha', 0) >= 1.0:
        criteria_met.append("سكور ألفا ≥ 1.0")
    else:
        missing.append(f"سكور ألفا ({candidate.get('alpha', 0):.3f})")
    
    if candidate.get('target_pct', 0) >= 8:
        criteria_met.append("هدف ≥ 8%")
    else:
        missing.append(f"هدف ({candidate.get('target_pct', 0):.1f}%)")
    
    if candidate.get('strategy_points', 0) >= 2:
        criteria_met.append("نقاط استراتيجية ≥ 2")
    else:
        missing.append(f"نقاط استراتيجية ({candidate.get('strategy_points', 0)})")
    
    if candidate.get('volume_confirm', False):
        criteria_met.append("تأكيد حجم ✅")
    else:
        missing.append("تأكيد حجم ❌")
    
    if candidate.get('trend_confirm', False):
        criteria_met.append("تأكيد اتجاه ✅")
    else:
        missing.append("تأكيد اتجاه ❌")
    
    return len(criteria_met) >= 4, criteria_met, missing

# =========================================================
# تأكيد الزخم متعدد الدورات
# =========================================================
def check_momentum_confirmation(tracker, min_appearances=2):
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
# نظام كيلي للمخاطرة
# =========================================================
def calculate_kelly_position_size(cash, win_rate, avg_win_pct, avg_loss_pct, base_risk=0.04):
    if win_rate <= 0 or avg_win_pct <= 0 or avg_loss_pct <= 0:
        return cash * base_risk
    
    win_rate_decimal = win_rate / 100.0
    avg_win_decimal = avg_win_pct / 100.0
    avg_loss_decimal = abs(avg_loss_pct) / 100.0
    
    b = avg_win_decimal / avg_loss_decimal
    p = win_rate_decimal
    q = 1 - p
    
    kelly_fraction = (p * b - q) / b
    kelly_fraction = max(0, min(kelly_fraction, 0.25))
    kelly_fraction = kelly_fraction * KELLY_FRACTION
    
    if kelly_fraction <= 0.01:
        return cash * base_risk
    
    return cash * kelly_fraction

# =========================================================
# تنبيهات الانحرافات
# =========================================================
def check_anomalies(trader):
    global is_paused, auto_paused_reason
    
    if len(trader.closed_trades) < 5:
        return False, None
    
    recent_trades = trader.closed_trades[-MAX_CONSECUTIVE_LOSSES:]
    consecutive_losses = all(t['pnl'] <= 0 for t in recent_trades)
    
    if consecutive_losses:
        return True, f"{MAX_CONSECUTIVE_LOSSES} صفقات خاسرة متتالية"
    
    if trader.initial_capital > 0:
        drawdown = (trader.initial_capital - trader.cash) / trader.initial_capital
        if drawdown > MAX_DRAWDOWN_PCT:
            return True, f"تراجع {drawdown*100:.1f}% من رأس المال"
    
    if len(trader.closed_trades) >= 20:
        last_20 = trader.closed_trades[-20:]
        wins = sum(1 for t in last_20 if t['pnl'] > 0)
        win_rate = wins / 20
        if win_rate < 0.35:
            return True, f"نسبة نجاح منخفضة ({win_rate*100:.0f}%) في آخر 20 صفقة"
    
    return False, None

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

async def fetch_ticker_fast(exchange, symbol):
    try:
        ticker = await exchange.fetch_ticker(symbol)
        if not ticker:
            return None
        bid_volume = ticker.get('bidVolume', 0) or 0
        ask_volume = ticker.get('askVolume', 0) or 0
        obi = (bid_volume - ask_volume) / (bid_volume + ask_volume) if (bid_volume + ask_volume) > 0 else 0
        return {
            'symbol': symbol,
            'volume_24h': ticker.get('quoteVolume', 0) or 0,
            'high': ticker.get('high', 0) or 0,
            'low': ticker.get('low', 0) or 0,
            'close': ticker.get('close', 0) or 0,
            'obi': obi,
            'change_24h': ticker.get('percentage', 0) or 0
        }
    except:
        return None

# =========================================================
# حساب السكور والمؤشرات
# =========================================================
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
        if tsi_val > 0: score += 10
        if tsi_val > 10: score += 5
    
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
    if obi > 0.1: points += 1
    elif obi > 0.2: points += 2
    
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
                    'Filter Score', 'Strategy Points', 'Status', 'Close Time', 'Evaluation', 'Virtual PNL %'
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
            except Exception as e:
                print(f"⚠️ خطأ في تحديث سعر {cand['symbol']}: {e}")
        
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
                print(f"⏰ {cand['symbol']} انتهت صلاحيتها")
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
    def __init__(self, initial_capital=1000):
        self.initial_capital = initial_capital
        self.cash = initial_capital
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
                                 'PNL ($)', 'PNL (%)', 'Exit Reason', 'Alpha', 'Target %', 'Signal Type'])
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

    def get_kelly_stats(self):
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

    def open_position(self, signal, exchange, signal_type='alpha'):
        symbol = signal['symbol']
        entry_price = signal['entry_price']
        target_pct = signal.get('target_pct', 10)
        alpha = signal.get('alpha', 0)
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

        stop_loss = entry_price - (2.5 * atr)
        take_profit = entry_price * (1 + target_pct / 100)

        win_rate, avg_win, avg_loss = self.get_kelly_stats()
        if win_rate and avg_win and avg_loss:
            position_value = calculate_kelly_position_size(self.cash, win_rate, avg_win, avg_loss, 0.04)
        else:
            position_value = self.cash * 0.04

        position_value = min(position_value, self.cash * 0.95)
        position_value = max(position_value, 50)

        if position_value > self.cash:
            return False

        amount = position_value / entry_price

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
            'signal_type': signal_type
        }
        self.positions.append(position)

        msg = (f"🟢 صفقة جديدة ({signal_type}): {symbol}\n"
               f"سعر الدخول: {entry_price:.4f}\n"
               f"قيمة: {position_value:.2f}$ | كمية: {amount:.4f}\n"
               f"🛑 وقف: {stop_loss:.4f} | 🎯 هدف: {take_profit:.4f}\n"
               f"📈 صعود: {target_pct:.2f}% | ⏱️ {eta_str}\n"
               f"💰 الرصيد: {self.cash:.2f}$")
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
            trailing_stop = pos['highest_price'] - (2.5 * atr_value)

            if not pos['breakeven_activated'] and price >= pos['entry_price'] * 1.02:
                pos['breakeven_activated'] = True
                trailing_stop = max(trailing_stop, pos['entry_price'])

            if trailing_stop > pos['current_stop']:
                pos['current_stop'] = trailing_stop

            final_stop = pos['current_stop']

            if price <= final_stop:
                reason = "وقف خسارة متحرك"
                if pos['breakeven_activated'] and final_stop >= pos['entry_price']:
                    reason = "وقف خسارة (تعادل)"
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
            'signal_type': pos.get('signal_type', 'unknown')
        }
        self.closed_trades.append(trade_record)
        self._append_trade_to_csv(trade_record)

        msg = f"🔴 إغلاق {pos['symbol']}: {reason} | ربح = {pnl:.2f}$ ({pnl_pct:.2f}%) | الرصيد = {self.cash:.2f}$"
        print(msg)
        asyncio.create_task(send_telegram_message(msg))
        self.save_state()

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
                f"{trade['pnl_pct']:.2f}%",
                trade['exit_reason'],
                f"{trade.get('alpha', 0):.3f}",
                f"{trade.get('target_pct', 0):.2f}%",
                trade.get('signal_type', 'unknown')
            ])

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
        report += f"📋 صفقات: {stats['total_trades']} | ✅ {stats['win_count']} | ❌ {stats['loss_count']}\n"
        report += f"🎯 نجاح: {stats['win_rate']:.2f}% | 🔓 مفتوحة: {stats['open_positions']}\n"
        if self.positions and current_prices:
            report += "\n📌 الصفقات المفتوحة:\n"
            for pos in self.positions:
                sym = pos['symbol']
                cp = current_prices.get(sym, pos['entry_price'])
                pnl = (cp - pos['entry_price']) * pos['amount']
                pnl_pct = ((cp / pos['entry_price']) - 1) * 100
                report += f"  - {sym}: {pos['entry_price']:.4f} → {cp:.4f} | {pnl:.2f}$ ({pnl_pct:.2f}%)\n"
        return report

# =========================================================
# أوامر الإيقاف المؤقت
# =========================================================
async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_paused, pause_until_time, auto_paused_reason
    is_paused = True
    pause_until_time = None
    auto_paused_reason = "يدوي"
    await update.message.reply_text("⏸️ تم إيقاف فتح الصفقات الجديدة.")

async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_paused, pause_until_time, auto_paused_reason
    is_paused = False
    pause_until_time = None
    auto_paused_reason = None
    await update.message.reply_text("▶️ تم استئناف فتح الصفقات.")

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
# المسح والتحليل
# =========================================================
async def batched_lightning_scan(exchange, symbols_to_scan, min_volume=200000, min_volatility=0.015):
    print(f"⚡ بدء المسح لـ {len(symbols_to_scan)} عملة...")

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

        print(f"   ✅ دفعة {batch_num+1}/{total_batches} ({len(passed)} عملة)")

        if batch_num < total_batches - 1:
            await asyncio.sleep(BATCH_DELAY)

    print(f"✅ اكتمل المسح: {len(passed)} عملة")
    return passed

# =========================================================
# بوت تيليجرام
# =========================================================
async def run_telegram_bot():
    global telegram_app
    telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()
    telegram_app.add_handler(CommandHandler("status", status_command))
    telegram_app.add_handler(CommandHandler("pause", pause_command))
    telegram_app.add_handler(CommandHandler("resume", resume_command))
    print("🤖 بوت Telegram قيد التشغيل...")
    await telegram_app.run_polling()

# =========================================================
# حلقة التداول الرئيسية
# =========================================================
async def trading_loop():
    global exchange_sync_instance, candidate_tracker, current_cycle, all_symbols
    global is_paused, pause_until_time, auto_paused_reason, trader_instance

    exchange_async = ccxt_async.gateio({'enableRateLimit': True})
    exchange_sync = ccxt.gateio({'enableRateLimit': True})
    exchange_sync_instance = exchange_sync

    markets = await exchange_async.load_markets()
    if markets:
        all_symbols = [s for s in markets if s.endswith('/USDT') and '.d' not in s]
        print(f"📋 تم تحميل {len(all_symbols)} عملة")
    else:
        print("❌ فشل تحميل العملات")
        return

    trader = PaperTrader(initial_capital=INITIAL_CAPITAL)
    trader_instance = trader
    tracker = CandidateTracker()
    candidate_tracker = tracker

    reject_reasons = {
        "volume_spike": 0, "filter_score": 0, "strategy": 0,
        "cold_market": 0, "high_change_24h": 0,
        "volume_confirm": 0, "trend_confirm": 0, "high_volatility": 0
    }

    last_report = time.time()
    last_candidates_sent = time.time()
    last_backup = time.time()
    last_price_update = 0

    print(f"🤖 بدء التداول - {datetime.now()}\n")
    await asyncio.sleep(2)
    await send_telegram_message("🚀 بوت التداول الورقي (الإصدار النهائي) بدأ العمل!")

    while True:
        try:
            current_time = time.time()

            # ⭐ تحديث الأسعار كل دقيقة
            if current_time - last_price_update >= PRICE_UPDATE_INTERVAL:
                tracker.update_prices(exchange_sync)
                tracker.evaluate_and_close()

                prices = {}
                for pos in trader.positions:
                    try:
                        ticker = exchange_sync.fetch_ticker(pos['symbol'])
                        if ticker:
                            prices[pos['symbol']] = ticker['last']
                    except:
                        pass
                trader.update_positions(prices)

                last_price_update = current_time

            # فحص الإيقاف المؤقت
            if is_paused:
                if pause_until_time and datetime.now() >= pause_until_time:
                    is_paused = False
                    pause_until_time = None
                    auto_paused_reason = None
                    await send_telegram_message("▶️ تم استئناف التداول تلقائياً.")
                else:
                    await asyncio.sleep(10)
                    continue

            # فحص الانحرافات
            if not is_paused:
                has_anomaly, anomaly_reason = check_anomalies(trader)
                if has_anomaly:
                    is_paused = True
                    auto_paused_reason = f"تلقائي: {anomaly_reason}"
                    await send_telegram_message(f"🚨 تنبيه انحراف!\n{anomaly_reason}\nتم الإيقاف التلقائي.")

            # ⭐ مسح كل 30 دقيقة
            if current_time - last_candidates_sent >= SCAN_INTERVAL:
                # اختيار مجموعة العملات
                total_symbols = len(all_symbols)
                if current_cycle == 1:
                    symbols_to_scan = all_symbols[:SYMBOLS_PER_CYCLE]
                    print(f"\n🔄 دورة 1: {len(symbols_to_scan)} عملة")
                    current_cycle = 2
                else:
                    start_idx = SYMBOLS_PER_CYCLE
                    end_idx = min(start_idx + SYMBOLS_PER_CYCLE, total_symbols)
                    symbols_to_scan = all_symbols[start_idx:end_idx]
                    print(f"\n🔄 دورة 2: {len(symbols_to_scan)} عملة")
                    current_cycle = 1

                results = await batched_lightning_scan(exchange_async, symbols_to_scan)

                if results:
                    market_ctx = detect_market_regime(exchange_sync)

                    if market_ctx.get('regime') == 'COLD':
                        print("⚠️ سوق بارد، تخطي الصفقات")
                        reject_reasons["cold_market"] += 1
                    else:
                        candidates = []
                        for item in results:
                            df = fetch_ohlcv_sync(exchange_sync, item['symbol'], '5m', 40)
                            if df.empty:
                                continue

                            last_volume = df['volume'].iloc[-1]
                            avg_volume_20 = df['volume'].rolling(20).mean().iloc[-1]
                            if pd.isna(avg_volume_20) or last_volume < avg_volume_20 * 1.5:
                                reject_reasons["volume_spike"] += 1
                                continue

                            fs, filter_details = calculate_filter_score(df)
                            if fs < 15:
                                reject_reasons["filter_score"] += 1
                                continue

                            obi = item.get('obi', 0)
                            sp, strategy_details = check_strategies_weighted(df, obi)
                            if sp < 1:
                                reject_reasons["strategy"] += 1
                                continue

                            vol_confirm, _ = check_volume_confirmation(df)
                            if not vol_confirm:
                                reject_reasons["volume_confirm"] += 1
                                continue

                            trend_confirm, _ = check_trend_confirmation(df)
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
                                'volume_confirm': vol_confirm,
                                'trend_confirm': trend_confirm
                            }
                            candidates.append(cand)

                        if candidates:
                            candidates.sort(key=lambda x: x['final_rank'], reverse=True)

                            positions_opened = 0
                            MAX_POSITIONS_PER_CYCLE = 3

                            # ⭐ أولوية 1: انفجار وشيك
                            for cand in candidates[:TOP_CANDIDATES_COUNT]:
                                if positions_opened >= MAX_POSITIONS_PER_CYCLE:
                                    break
                                is_explosive, criteria_met, _ = check_explosion_criteria(cand)
                                if is_explosive:
                                    msg = f"🔥🔥🔥 انفجار وشيك!\n{cand['symbol']}\nسعر: {cand['entry_price']:.4f}\nألفا: {cand['alpha']:.3f}\nهدف: {cand['target_pct']:.2f}%\n✅ {criteria_met}/5 معايير"
                                    asyncio.create_task(send_telegram_message(msg))

                                    already_open = any(p['symbol'] == cand['symbol'] for p in trader.positions)
                                    if not already_open and trader.cash > 50:
                                        df = cand['df']
                                        if df is not None and len(df) > 14:
                                            atr_series = manual_atr(df['high'], df['low'], df['close'])
                                            atr = atr_series.iloc[-1] if not atr_series.empty else cand['entry_price'] * 0.03
                                        else:
                                            atr = cand['entry_price'] * 0.03
                                        cand['stop_loss'] = cand['entry_price'] - (2.5 * atr)
                                        cand['take_profit'] = cand['entry_price'] * (1 + cand['target_pct'] / 100)

                                        if trader.open_position(cand, exchange_sync, signal_type='explosion'):
                                            positions_opened += 1

                            # تحضير للتأكيد متعدد الدورات
                            for cand in candidates[:TOP_CANDIDATES_COUNT]:
                                df = cand['df']
                                if df is not None and len(df) > 14:
                                    atr_series = manual_atr(df['high'], df['low'], df['close'])
                                    atr = atr_series.iloc[-1] if not atr_series.empty else cand['entry_price'] * 0.03
                                else:
                                    atr = cand['entry_price'] * 0.03
                                cand['stop_loss'] = cand['entry_price'] - (2.5 * atr)
                                cand['take_profit'] = cand['entry_price'] * (1 + cand['target_pct'] / 100)

                            tracker.add_candidates(candidates[:TOP_CANDIDATES_COUNT], datetime.now())

                            confirmed_momentum = check_momentum_confirmation(tracker, MIN_APPEARANCES)
                            for cand in confirmed_momentum:
                                if positions_opened >= MAX_POSITIONS_PER_CYCLE:
                                    break
                                msg = f"🚀🚀🚀 تأكيد زخم!\n{cand['symbol']} ظهرت {MIN_APPEARANCES} مرات متتالية!\nسعر: {cand['entry_price']:.4f}\nهدف: {cand['target_pct']:.2f}%"
                                asyncio.create_task(send_telegram_message(msg))

                                already_open = any(p['symbol'] == cand['symbol'] for p in trader.positions)
                                if not already_open and trader.cash > 50:
                                    if trader.open_position(cand, exchange_sync, signal_type='momentum'):
                                        positions_opened += 1

                            # ⭐ أولوية 3: عملة جيدة
                            for cand in candidates[:TOP_CANDIDATES_COUNT]:
                                if positions_opened >= MAX_POSITIONS_PER_CYCLE:
                                    break
                                is_good, criteria_met, missing = check_good_coin_criteria(cand)
                                if is_good:
                                    already_open = any(p['symbol'] == cand['symbol'] for p in trader.positions)
                                    if not already_open and trader.cash > 50:
                                        if trader.open_position(cand, exchange_sync, signal_type='good_coin'):
                                            positions_opened += 1

                            # إرسال قائمة الترشيحات
                            msg = f"📋 أفضل {TOP_CANDIDATES_COUNT} ترشيحات:\n\n"
                            for i, c in enumerate(candidates[:TOP_CANDIDATES_COUNT], 1):
                                msg += f"{i}. {c['symbol']} | {c['entry_price']:.4f} | ألفا: {c['alpha']:.3f} | هدف: {c['target_pct']:.2f}%\n"
                            asyncio.create_task(send_telegram_message(msg))

                last_candidates_sent = current_time

            # تقرير كل ساعة
            if current_time - last_report >= 3600:
                prices = {}
                for pos in trader.positions:
                    try:
                        ticker = exchange_sync.fetch_ticker(pos['symbol'])
                        if ticker:
                            prices[pos['symbol']] = ticker['last']
                    except:
                        pass

                report = trader.generate_report(prices)
                if report:
                    stats = tracker.get_statistics()
                    if stats:
                        report += f"\n📊 ترشيحات: ✅ {stats['success']} | ❌ {stats['fail']} | 🎯 {stats['success_rate']:.1f}%"
                    asyncio.create_task(send_telegram_message(report))

                if os.path.exists(trader.trades_csv):
                    asyncio.create_task(send_csv_file(trader.trades_csv, "📁 صفقات مغلقة"))
                if os.path.exists(tracker.candidates_csv):
                    asyncio.create_task(send_csv_file(tracker.candidates_csv, "📁 ترشيحات العملات"))

                for key in reject_reasons:
                    reject_reasons[key] = 0
                last_report = current_time

            # نسخ احتياطي كل 24 ساعة
            if current_time - last_backup >= 86400:
                backup_files()
                last_backup = current_time

            await asyncio.sleep(5)

        except KeyboardInterrupt:
            print("\n👋 إيقاف...")
            await send_telegram_message("⏹️ تم إيقاف البوت.")
            break
        except Exception as e:
            print(f"❌ خطأ: {e}")
            await asyncio.sleep(60)

    await exchange_async.close()

async def main():
    global telegram_app
    telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()
    await telegram_app.initialize()
    print("🤖 تطبيق Telegram جاهز...")

    await asyncio.gather(
        run_telegram_bot(),
        trading_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())
