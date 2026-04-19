"""
نظام التداول الورقي المتكامل - النسخة النهائية الكاملة
التحسينات المدمجة:
- مؤشر TSI للزخم غير المتأخر
- فلتر ميل EMA لتأكيد الاختراقات
- محاكاة OBI باستخدام بيانات Bid/Ask
- وقف خسارة متحرك معتمد على ATR (يتكيف مع تقلب العملة)
- تأمين الأرباح: نقل الوقف إلى نقطة الدخول عند ربح 2%
- تجنب العملات مرتفعة الارتفاع (>50% خلال 24 ساعة)
- آلية إعادة المحاولة (Retry Logic) لموثوقية API
- إشعار خاص للعملات التي تحقق معايير الانفجار القوي (5/5)
- نظام تأكيد الزخم عبر 3 دورات متتالية
- حجم صفقة ديناميكي مرتبط بجودة الإشارة ونسبة الصعود
- مدة مسح 3 دقائق (استجابة أسرع)
"""

import asyncio
import ccxt.async_support as ccxt_async
import ccxt
import pandas as pd
import numpy as np
import time
from datetime import datetime
import json
import os
import csv
from telegram.ext import Application

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
MAX_POSITIONS = 10  # زدنا الحد لاستيعاب تقسيم رأس المال الجديد
MIN_APPEARANCES = 3  # عدد مرات الظهور للتأكيد

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
# فحص معايير الانفجار القوي
# =========================================================
def check_explosion_criteria(candidate):
    score = 0
    if candidate.get('filter_score', 0) >= 75:
        score += 1
    if candidate.get('alpha', 0) >= 1.8:
        score += 1
    if candidate.get('target_pct', 0) >= 18:
        score += 1
    eta_bars = candidate.get('eta_bars', 999)
    if eta_bars and eta_bars <= 48:
        score += 1
    if candidate.get('strategy_points', 0) >= 7:
        score += 1
    return score >= 5, score

# =========================================================
# فحص تأكيد الزخم متعدد الدورات
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
# حساب حجم الصفقة الديناميكي
# =========================================================
def calculate_dynamic_position_size(signal_type, cash, entry_price, stop_loss, target_pct, alpha=0):
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
    
    return position_value

# =========================================================
# الدوال المساعدة
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

# =========================================================
# بوت الانفجار
# =========================================================
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

async def lightning_scan(exchange, min_volume=500000, min_volatility=0.015):
    markets = await fetch_with_retry(exchange.load_markets)
    if not markets:
        return []
    symbols = [s for s in markets if s.endswith('/USDT') and '.d' not in s]
    print(f"⚡ بدء المسح الخاطف لـ {len(symbols)} عملة...")

    tasks = [fetch_ticker_fast(exchange, sym) for sym in symbols]
    results = await asyncio.gather(*tasks)

    passed = []
    for r in results:
        if r is None or r['close'] <= 0:
            continue
        volatility = (r['high'] - r['low']) / r['close'] if r['close'] > 0 else 0
        
        if r['change_24h'] > 50:
            continue
            
        if r['volume_24h'] >= min_volume and volatility >= min_volatility:
            r['volatility'] = volatility
            passed.append(r)
    print(f"✅ اجتاز الفلترة السريعة {len(passed)} عملة")
    return passed

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
# متتبع الترشيحات (مع تتبع عدد الظهور)
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
                    'Target %', 'Alpha', 'ETA', 'Status', 'Close Time', 'Final Price', 'Result', 'PNL %'
                ])

    def add_candidates(self, candidates_list, scan_time):
        # تحديث عداد الظهور
        for cand in candidates_list[:3]:
            symbol = cand['symbol']
            self.appearance_count[symbol] = self.appearance_count.get(symbol, 0) + 1
        
        # تنظيف العداد للعملات التي لم تعد في القائمة
        current_symbols = {c['symbol'] for c in candidates_list[:3]}
        for symbol in list(self.appearance_count.keys()):
            if symbol not in current_symbols:
                self.appearance_count[symbol] = 0
        
        # تسجيل المرشحين النشطين
        for rank, cand in enumerate(candidates_list[:3], 1):
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
                'status': 'ACTIVE',
                'close_time': None,
                'final_price': None,
                'result': None,
                'pnl_pct': None
            }
            self.active_candidates.append(record)
            self._write_record(record)

    def _write_record(self, record):
        with open(self.candidates_csv, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
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
                record['status'],
                record['close_time'].isoformat() if record['close_time'] else '',
                f"{record['final_price']:.4f}" if record['final_price'] else '',
                record['result'] or '',
                f"{record['pnl_pct']:.2f}" if record['pnl_pct'] is not None else ''
            ])

    def update_candidates(self, current_prices, max_age_hours=24):
        now = datetime.now()
        for cand in self.active_candidates:
            if cand['status'] != 'ACTIVE':
                continue
            symbol = cand['symbol']
            if symbol not in current_prices:
                continue
            price = current_prices[symbol]
            age = (now - cand['scan_time']).total_seconds() / 3600
            if age > max_age_hours:
                cand['status'] = 'EXPIRED'
                cand['close_time'] = now
                cand['final_price'] = price
                cand['result'] = 'EXPIRED'
                cand['pnl_pct'] = ((price - cand['entry_price']) / cand['entry_price']) * 100
                self._write_record(cand)
                continue
            if price <= cand['stop_loss']:
                cand['status'] = 'CLOSED'
                cand['close_time'] = now
                cand['final_price'] = price
                cand['result'] = 'STOP_LOSS'
                cand['pnl_pct'] = ((price - cand['entry_price']) / cand['entry_price']) * 100
                self._write_record(cand)
            elif price >= cand['take_profit']:
                cand['status'] = 'CLOSED'
                cand['close_time'] = now
                cand['final_price'] = price
                cand['result'] = 'TAKE_PROFIT'
                cand['pnl_pct'] = ((price - cand['entry_price']) / cand['entry_price']) * 100
                self._write_record(cand)
        self.active_candidates = [c for c in self.active_candidates if c['status'] == 'ACTIVE']

# =========================================================
# نظام التداول الورقي (مع حجم صفقة ديناميكي)
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
                                 'PNL ($)', 'PNL (%)', 'Exit Reason', 'Alpha', 'Target %', 'ETA', 'Signal Type'])
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
                trade.get('signal_type', 'unknown')
            ])

    def open_position(self, signal, exchange, signal_type='alpha'):
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
        atr_multiplier = 3.0
        stop_loss = entry_price - (atr_multiplier * atr)
        take_profit = entry_price * (1 + target_pct / 100)
        
        # حساب حجم الصفقة الديناميكي
        position_value = calculate_dynamic_position_size(
            signal_type, self.cash, entry_price, stop_loss, target_pct, alpha
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
            'signal_type': signal_type
        }
        self.positions.append(position)

        msg = (f"🟢 صفقة جديدة ({signal_type}): {symbol}\n"
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
            'signal_type': pos.get('signal_type', 'unknown')
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
# حلقة التداول الرئيسية
# =========================================================
async def trading_loop():
    global exchange_sync_instance, candidate_tracker

    exchange_async = ccxt_async.gateio({'enableRateLimit': True})
    exchange_sync = ccxt.gateio({'enableRateLimit': True})
    exchange_sync_instance = exchange_sync

    trader = PaperTrader(initial_capital=INITIAL_CAPITAL, max_positions=MAX_POSITIONS)

    tracker = CandidateTracker()
    candidate_tracker = tracker

    reject_reasons = {
        "volume_spike": 0,
        "filter_score": 0,
        "strategy": 0,
        "cold_market": 0,
        "insufficient_cash": 0,
        "high_change_24h": 0
    }

    last_report = time.time()
    last_candidates_sent = time.time()
    print(f"🤖 بدء التداول الورقي المحسّن - {datetime.now()}\n")
    await asyncio.sleep(2)
    await send_telegram_message("🚀 بوت التداول الورقي (النسخة النهائية الكاملة) بدأ العمل!")

    while True:
        try:
            results = await lightning_scan(exchange_async)
            if not results:
                await asyncio.sleep(60)
                continue

            market_ctx = detect_market_regime(exchange_sync)

            if market_ctx.get('regime') == 'COLD':
                print("⚠️ السوق بارد (COLD)، تم تخطي فتح الصفقات")
                reject_reasons["cold_market"] += 1
                await asyncio.sleep(180)
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

                fs = calculate_filter_score(df)
                if fs < 30:
                    reject_reasons["filter_score"] += 1
                    continue

                obi = item.get('obi', 0)
                sp = check_strategies_weighted(df, obi)
                if sp < 3:
                    reject_reasons["strategy"] += 1
                    continue

                alpha = calculate_enhanced_alpha(df, market_ctx, obi)
                target_pct = calculate_target_percentage(df)
                last_price = df['close'].iloc[-1]
                target_price = last_price * (1 + target_pct / 100)
                eta_bars = calculate_blended_eta(df, target_price)
                eta_str = format_eta(eta_bars)
                final_rank = (alpha * 0.7) + (target_pct / 100 * 0.3)
                
                candidates.append({
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
                    'strategy_points': sp
                })

            if not candidates:
                await asyncio.sleep(180)
                continue

            candidates.sort(key=lambda x: x['final_rank'], reverse=True)

            # ===== أولوية 1: فحص الانفجار الوشيك =====
            for cand in candidates[:3]:
                is_explosive, criteria_met = check_explosion_criteria(cand)
                if is_explosive:
                    msg = f"🔥🔥🔥 تنبيه انفجار وشيك 🔥🔥🔥\n\n"
                    msg += f"{cand['symbol']}\n"
                    msg += f"سعر الدخول: {cand['entry_price']:.4f}\n"
                    msg += f"سكور ألفا: {cand['alpha']:.3f}\n"
                    msg += f"نسبة الصعود: {cand['target_pct']:.2f}%\n"
                    msg += f"الوقت المتوقع: {cand['eta_str']}\n"
                    msg += f"نقاط الاستراتيجية: {cand['strategy_points']}/10\n"
                    msg += f"سكور الفلتر: {cand['filter_score']}/100\n"
                    msg += f"\n⚠️ هذه العملة تحقق {criteria_met}/5 من معايير الانفجار القوي"
                    asyncio.create_task(send_telegram_message(msg))
                    
                    # فتح صفقة فورية
                    already_open = any(p['symbol'] == cand['symbol'] for p in trader.positions)
                    if not already_open and trader.cash > 50 and len(trader.positions) < trader.max_positions:
                        # حساب وقف الخسارة والهدف
                        df = cand['df']
                        if df is not None and len(df) > 14:
                            atr_series = manual_atr(df['high'], df['low'], df['close'])
                            atr = atr_series.iloc[-1] if not atr_series.empty else cand['entry_price'] * 0.03
                        else:
                            atr = cand['entry_price'] * 0.03
                        cand['stop_loss'] = cand['entry_price'] - (3.0 * atr)
                        cand['take_profit'] = cand['entry_price'] * (1 + cand['target_pct'] / 100)
                        
                        trader.open_position(cand, exchange_sync, signal_type='explosion')

            # ===== أولوية 2: فحص تأكيد الزخم متعدد الدورات =====
            for cand in candidates[:3]:
                df = cand['df']
                if df is not None and len(df) > 14:
                    atr_series = manual_atr(df['high'], df['low'], df['close'])
                    atr = atr_series.iloc[-1] if not atr_series.empty else cand['entry_price'] * 0.03
                else:
                    atr = cand['entry_price'] * 0.03
                cand['stop_loss'] = cand['entry_price'] - (3.0 * atr)
                cand['take_profit'] = cand['entry_price'] * (1 + cand['target_pct'] / 100)

            tracker.add_candidates(candidates[:3], datetime.now())
            
            confirmed_momentum = check_momentum_confirmation(tracker, MIN_APPEARANCES)
            for cand in confirmed_momentum:
                msg = f"🚀🚀🚀 تأكيد زخم متعدد الدورات 🚀🚀🚀\n\n"
                msg += f"{cand['symbol']} ظهرت في أفضل 3 ترشيحات لـ {MIN_APPEARANCES} دورات متتالية!\n"
                msg += f"سعر الدخول: {cand['entry_price']:.4f}\n"
                msg += f"نسبة الصعود: {cand['target_pct']:.2f}%\n"
                msg += f"سكور ألفا: {cand['alpha']:.3f}"
                asyncio.create_task(send_telegram_message(msg))
                
                already_open = any(p['symbol'] == cand['symbol'] for p in trader.positions)
                if not already_open and trader.cash > 50 and len(trader.positions) < trader.max_positions:
                    trader.open_position(cand, exchange_sync, signal_type='momentum')

            # ===== أولوية 3: أفضل مرشح (أعلى سكور) =====
            best = candidates[0]
            print(f"\n🏆 أفضل مرشح: {best['symbol']} | سعر {best['entry_price']:.4f} | ألفا {best['alpha']:.3f} | هدف {best['target_pct']:.2f}%")
            
            # فتح صفقة على أفضل مرشح إذا كان يستحق ولم تفتح صفقات أخرى كثيرة
            if best['alpha'] >= 2.0 and best['target_pct'] >= 15:
                already_open = any(p['symbol'] == best['symbol'] for p in trader.positions)
                if not already_open and trader.cash > 50 and len(trader.positions) < trader.max_positions - 2:
                    trader.open_position(best, exchange_sync, signal_type='alpha')

            # إرسال قائمة الترشيحات كل 18 دقيقة (1080 ثانية)
            if time.time() - last_candidates_sent >= 1080:
                msg = "📋 أفضل 3 ترشيحات حالياً:\n\n"
                for i, c in enumerate(candidates[:3], 1):
                    msg += f"{i}. {c['symbol']} | سعر: {c['entry_price']:.4f} | ألفا: {c['alpha']:.3f} | هدف: {c['target_pct']:.2f}% | ETA: {c['eta_str']}\n"
                asyncio.create_task(send_telegram_message(msg))
                last_candidates_sent = time.time()

            # تحديث أسعار الصفقات المفتوحة
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

            for cand in candidates[:3]:
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
                    reject_msg = f"\n📊 أسباب الرفض: حجم شمعة={reject_reasons['volume_spike']}, سكور={reject_reasons['filter_score']}, استراتيجية={reject_reasons['strategy']}, سوق بارد={reject_reasons['cold_market']}, ارتفاع >50%={reject_reasons['high_change_24h']}"
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

            await asyncio.sleep(180)  # 3 دقائق

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
    print("🤖 تطبيق Telegram جاهز للإرسال...")

    await trading_loop()

    await telegram_app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
