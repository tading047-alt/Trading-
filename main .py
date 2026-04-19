"""
نظام التداول الورقي المتكامل - النسخة النهائية
- إشعارات تلقائية إلى قناة تيليجرام
- تتبع أفضل 3 مرشحين
- حفظ CSV للصفقات والتقارير
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
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# =========================================================
# إعدادات تيليجرام من متغيرات البيئة
# =========================================================
TELEGRAM_TOKEN = "8439548325:AAHOBBHy7EwcX3J5neIaf6iJuSjyGJCuZ68"
TELEGRAM_CHAT_ID = "5067771509"

async def send_telegram_message(text: str):
    """إرسال رسالة إلى القناة المحددة"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ لم يتم إعداد تيليجرام بشكل كامل")
        return
    try:
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        await app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
    except Exception as e:
        print(f"خطأ في إرسال رسالة تيليجرام: {e}")

# =========================================================
# المؤشرات الفنية - تنفيذ يدوي كامل
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

def fetch_ohlcv_sync(exchange, symbol, timeframe='5m', limit=60):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except:
        return pd.DataFrame()

# =========================================================
# بوت الانفجار (Explosion Bot)
# =========================================================
async def fetch_ticker_fast(exchange, symbol):
    try:
        ticker = await exchange.fetch_ticker(symbol)
        return {
            'symbol': symbol,
            'volume_24h': ticker.get('quoteVolume', 0) or 0,
            'high': ticker.get('high', 0) or 0,
            'low': ticker.get('low', 0) or 0,
            'close': ticker.get('close', 0) or 0
        }
    except:
        return None

async def lightning_scan(exchange, min_volume=500000, min_volatility=0.025):
    markets = await exchange.load_markets()
    symbols = [s for s in markets if s.endswith('/USDT') and '.d' not in s]
    print(f"⚡ بدء المسح الخاطف لـ {len(symbols)} عملة...")
    
    tasks = [fetch_ticker_fast(exchange, sym) for sym in symbols]
    results = await asyncio.gather(*tasks)
    
    passed = []
    for r in results:
        if r is None or r['close'] <= 0:
            continue
        volatility = (r['high'] - r['low']) / r['close'] if r['close'] > 0 else 0
        if r['volume_24h'] >= min_volume and volatility >= min_volatility:
            r['volatility'] = volatility
            passed.append(r)
    print(f"✅ اجتاز الفلترة السريعة {len(passed)} عملة")
    return passed

def calculate_filter_score(df):
    if df.empty or len(df) < 30:
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
    return score

def check_strategies_weighted(df):
    points = 0
    if df.empty or len(df) < 30:
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
    return points

def calculate_enhanced_alpha(df, market_context):
    if df.empty or len(df) < 30:
        return 0.0
    last = df.iloc[-1]
    avg_vol = df['volume'].rolling(20).mean().iloc[-1]
    vol_ratio = last['volume'] / avg_vol if avg_vol > 0 else 1.0
    atr_series = manual_atr(df['high'], df['low'], df['close'])
    atr = atr_series.iloc[-1] if not atr_series.empty else 0
    resistance = df['high'].rolling(20).max().iloc[-2]
    breakout_strength = (last['close'] - resistance) / atr if atr > 0 else 0
    def sigmoid(x, k=2): return 1 / (1 + np.exp(-k * x))
    z_vol = sigmoid(vol_ratio - 1.5, k=1.5)
    z_breakout = sigmoid(breakout_strength, k=2)
    depth_ratio = 1.0 + (vol_ratio / 10)
    z_depth = sigmoid(depth_ratio - 1.0, k=3)
    regime = market_context.get('regime', 'CALM')
    if regime == 'HOT':
        w_vol, w_break, w_depth = 0.3, 0.5, 0.2
    elif regime == 'COLD':
        w_vol, w_break, w_depth = 0.2, 0.3, 0.5
    else:
        w_vol, w_break, w_depth = 0.35, 0.35, 0.3
    raw_alpha = (z_vol * w_vol) + (z_breakout * w_break) + (z_depth * w_depth)
    beta_adj = -0.05 if regime == 'COLD' else (0.03 if regime == 'HOT' else 0.0)
    return round(raw_alpha + beta_adj, 4)

def calculate_target_percentage(df):
    if df.empty or len(df) < 30:
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
# متتبع الترشيحات (Candidate Tracker)
# =========================================================
class CandidateTracker:
    def __init__(self):
        self.candidates_csv = "scan_candidates.csv"
        self.active_candidates = []
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

    def get_recent(self, limit=5):
        if not os.path.exists(self.candidates_csv):
            return []
        df = pd.read_csv(self.candidates_csv)
        return df.tail(limit).to_dict('records')

# =========================================================
# نظام التداول الورقي مع حفظ CSV
# =========================================================
class PaperTrader:
    def __init__(self, initial_capital=1000, max_positions=10, risk_per_trade=0.02):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.max_positions = max_positions
        self.risk_per_trade = risk_per_trade
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
                                 'PNL ($)', 'PNL (%)', 'Exit Reason', 'Alpha', 'Target %', 'ETA'])
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
                trade.get('eta_str', 'N/A')
            ])

    def open_position(self, signal, exchange):
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
        atr_multiplier = 2.5
        stop_loss = entry_price - (atr_multiplier * atr)
        take_profit = entry_price * (1 + target_pct / 100)
        signal['stop_loss'] = stop_loss
        signal['take_profit'] = take_profit

        risk_amount = self.cash * self.risk_per_trade
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            return False
        amount = risk_amount / risk_per_unit
        try:
            market = exchange.market(symbol)
            min_amount = market['limits']['amount']['min']
            if amount < min_amount:
                amount = min_amount
        except:
            pass
        position_value = amount * entry_price
        if position_value > self.cash * 0.95:
            amount = (self.cash * 0.95) / entry_price
            position_value = amount * entry_price

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
            'highest_price': entry_price
        }
        self.positions.append(position)

        msg = (f"🟢 صفقة جديدة: {symbol}\n"
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
            if price <= pos['stop_loss']:
                to_close.append((i, price, "وقف خسارة"))
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
            'eta_str': pos.get('eta_str', 'N/A')
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
            return "📊 لا توجد صفقات مكتملة بعد."
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
# متغيرات عامة لـ Telegram
# =========================================================
trader_instance = None
exchange_sync_instance = None
candidate_tracker = None

# =========================================================
# بوت Telegram
# =========================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 بوت التداول الورقي\n\n"
        "الأوامر المتاحة:\n"
        "/status - عرض ملخص الحساب والصفقات المفتوحة\n"
        "/download_trades - تحميل ملف CSV للصفقات المغلقة\n"
        "/download_report - تحميل ملف CSV للتقرير الدوري\n"
        "/force_report - إنشاء تقرير فوري وحفظه\n"
        "/candidates - عرض آخر ترشيحات\n"
        "/download_candidates - تحميل ملف CSV للترشيحات"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if trader_instance is None:
        await update.message.reply_text("⚠️ نظام التداول غير مهيأ بعد.")
        return
    prices = {}
    if exchange_sync_instance:
        for pos in trader_instance.positions:
            try:
                ticker = exchange_sync_instance.fetch_ticker(pos['symbol'])
                prices[pos['symbol']] = ticker['last']
            except:
                prices[pos['symbol']] = pos['entry_price']
    stats = trader_instance.get_stats()
    if stats:
        msg = f"💰 الرصيد: {trader_instance.cash:.2f}$\n"
        msg += f"📈 العائد الإجمالي: {stats['total_pnl']:.2f}$ ({stats['total_return_pct']:.2f}%)\n"
        msg += f"📋 صفقات مغلقة: {stats['total_trades']} | ✅ {stats['win_count']} | ❌ {stats['loss_count']}\n"
        msg += f"🎯 نسبة النجاح: {stats['win_rate']:.2f}%\n"
        msg += f"🔓 صفقات مفتوحة: {stats['open_positions']}\n"
        if trader_instance.positions:
            msg += "\n📌 الصفقات المفتوحة:\n"
            for pos in trader_instance.positions:
                sym = pos['symbol']
                cp = prices.get(sym, pos['entry_price'])
                pnl = (cp - pos['entry_price']) * pos['amount']
                pnl_pct = ((cp / pos['entry_price']) - 1) * 100
                msg += f"  - {sym}: {pos['entry_price']:.4f} → {cp:.4f} | {pnl:.2f}$ ({pnl_pct:.2f}%)\n"
    else:
        msg = f"💰 الرصيد: {trader_instance.cash:.2f}$\n🔓 صفقات مفتوحة: {len(trader_instance.positions)}"
    await update.message.reply_text(msg)

async def download_trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if trader_instance is None:
        await update.message.reply_text("⚠️ نظام التداول غير مهيأ.")
        return
    csv_file = trader_instance.trades_csv
    if os.path.exists(csv_file):
        with open(csv_file, 'rb') as f:
            await update.message.reply_document(document=f, filename="closed_trades.csv", caption="📁 ملف الصفقات المغلقة")
    else:
        await update.message.reply_text("⚠️ لا يوجد ملف للصفقات بعد.")

async def download_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if trader_instance is None:
        await update.message.reply_text("⚠️ نظام التداول غير مهيأ.")
        return
    csv_file = trader_instance.report_csv
    if os.path.exists(csv_file):
        with open(csv_file, 'rb') as f:
            await update.message.reply_document(document=f, filename="hourly_report.csv", caption="📁 ملف التقارير الدورية")
    else:
        await update.message.reply_text("⚠️ لا يوجد ملف تقارير بعد.")

async def force_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if trader_instance is None:
        await update.message.reply_text("⚠️ نظام التداول غير مهيأ.")
        return
    prices = {}
    if exchange_sync_instance:
        for pos in trader_instance.positions:
            try:
                ticker = exchange_sync_instance.fetch_ticker(pos['symbol'])
                prices[pos['symbol']] = ticker['last']
            except:
                prices[pos['symbol']] = pos['entry_price']
    report = trader_instance.generate_report(prices)
    await update.message.reply_text(report[:4000])

async def candidates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if candidate_tracker is None:
        await update.message.reply_text("⚠️ نظام التتبع غير مهيأ.")
        return
    recent = candidate_tracker.get_recent(5)
    if not recent:
        await update.message.reply_text("📭 لا توجد ترشيحات مسجلة بعد.")
        return
    msg = "📋 آخر 5 ترشيحات:\n\n"
    for r in recent:
        msg += f"{r['Symbol']} (مرتبة {r['Rank']}) - {r['Status']}\n"
        msg += f"  دخول: {r['Entry Price']} | هدف: {r['Take Profit']} | وقف: {r['Stop Loss']}\n"
        if r['Result'] and pd.notna(r['Result']):
            msg += f"  نتيجة: {r['Result']} ({r['PNL %']}%)\n"
        msg += "\n"
    await update.message.reply_text(msg)

async def download_candidates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if candidate_tracker is None:
        await update.message.reply_text("⚠️ نظام التتبع غير مهيأ.")
        return
    csv_file = candidate_tracker.candidates_csv
    if os.path.exists(csv_file):
        with open(csv_file, 'rb') as f:
            await update.message.reply_document(document=f, filename="scan_candidates.csv", caption="📁 ملف ترشيحات العملات وتطور نتائجها")
    else:
        await update.message.reply_text("⚠️ لا يوجد ملف ترشيحات بعد.")

async def run_telegram_bot():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("download_trades", download_trades_command))
    app.add_handler(CommandHandler("download_report", download_report_command))
    app.add_handler(CommandHandler("force_report", force_report_command))
    app.add_handler(CommandHandler("candidates", candidates_command))
    app.add_handler(CommandHandler("download_candidates", download_candidates_command))
    print("🤖 بوت Telegram قيد التشغيل...")
    await app.run_polling()

# =========================================================
# حلقة التداول
# =========================================================
async def trading_loop():
    global trader_instance, exchange_sync_instance, candidate_tracker

    exchange_async = ccxt_async.gateio({'enableRateLimit': True})
    exchange_sync = ccxt.gateio({'enableRateLimit': True})
    exchange_sync_instance = exchange_sync

    trader = PaperTrader(initial_capital=1000, max_positions=10, risk_per_trade=0.02)
    trader_instance = trader

    tracker = CandidateTracker()
    candidate_tracker = tracker

    last_report = time.time()
    print(f"🤖 بدء التداول الورقي - {datetime.now()}\n")
    await send_telegram_message("🚀 بوت التداول الورقي بدأ العمل!")

    while True:
        try:
            results = await lightning_scan(exchange_async)
            if not results:
                await asyncio.sleep(60)
                continue

            market_ctx = detect_market_regime(exchange_sync)
            candidates = []
            for item in results:
                df = fetch_ohlcv_sync(exchange_sync, item['symbol'], '5m', 60)
                if df.empty:
                    continue
                fs = calculate_filter_score(df)
                if fs < 50:
                    continue
                sp = check_strategies_weighted(df)
                if sp < 5:
                    continue
                alpha = calculate_enhanced_alpha(df, market_ctx)
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
                    'final_rank': final_rank,
                    'df': df
                })

            if not candidates:
                await asyncio.sleep(60)
                continue

            candidates.sort(key=lambda x: x['final_rank'], reverse=True)

            for cand in candidates[:3]:
                df = cand['df']
                entry_price = cand['entry_price']
                if df is not None and len(df) > 14:
                    atr_series = manual_atr(df['high'], df['low'], df['close'])
                    atr = atr_series.iloc[-1] if not atr_series.empty else entry_price * 0.03
                else:
                    atr = entry_price * 0.03
                cand['stop_loss'] = entry_price - (2.5 * atr)
                cand['take_profit'] = entry_price * (1 + cand['target_pct'] / 100)

            tracker.add_candidates(candidates[:3], datetime.now())

            best = candidates[0]
            print(f"\n🏆 أفضل مرشح: {best['symbol']} | سعر {best['entry_price']:.4f} | ألفا {best['alpha']:.3f} | هدف {best['target_pct']:.2f}%")

            if trader.cash > 50 and len(trader.positions) < trader.max_positions:
                trader.open_position(best, exchange_sync)

            prices = {}
            for pos in trader.positions:
                try:
                    ticker = exchange_sync.fetch_ticker(pos['symbol'])
                    prices[pos['symbol']] = ticker['last']
                except:
                    prices[pos['symbol']] = pos['entry_price']
            trader.update_positions(prices)

            for cand in candidates[:3]:
                sym = cand['symbol']
                if sym not in prices:
                    try:
                        ticker = exchange_sync.fetch_ticker(sym)
                        prices[sym] = ticker['last']
                    except:
                        pass
            tracker.update_candidates(prices)

            if time.time() - last_report >= 3600:
                report = trader.generate_report(prices)
                print(report)
                asyncio.create_task(send_telegram_message(report))
                last_report = time.time()

            await asyncio.sleep(300)

        except KeyboardInterrupt:
            print("\n👋 إيقاف...")
            await send_telegram_message("⏹️ تم إيقاف البوت.")
            break
        except Exception as e:
            print(f"❌ خطأ: {e}")
            await asyncio.sleep(60)

    await exchange_async.close()

async def main():
    await asyncio.gather(
        run_telegram_bot(),
        trading_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())
