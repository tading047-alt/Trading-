"""
نظام التداول الورقي المتكامل - مع تتبع سعر العملات وتقييم الصفقات
الميزات الأساسية:
- تتبع سعر العملات المرشحة كل دقيقة
- تقييم افتراضي: نجاح (+6%) / فشل (-3%)
- تسجيل النتيجة كما لو كانت صفقة حقيقية
- تخفيف الفلاتر لزيادة عدد الفرص
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
TOP_CANDIDATES_COUNT = 5
BATCH_SIZE = 100
BATCH_DELAY = 2.5
SYMBOLS_PER_CYCLE = 500
SCAN_INTERVAL = 1800  # مسح كل 30 دقيقة
PRICE_UPDATE_INTERVAL = 60  # ⭐ تحديث الأسعار كل دقيقة

# ⭐ عتبات تقييم النتائج
FAIL_THRESHOLD = -0.03   # -3%
SUCCESS_THRESHOLD = 0.06  # +6%
MAX_AGE_HOURS = 24        # مدة المراقبة قبل اعتبارها منتهية

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

# =========================================================
# المؤشرات الفنية (نسخة مبسطة للتركيز على التتبع)
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
        return {
            'symbol': symbol,
            'volume_24h': ticker.get('quoteVolume', 0) or 0,
            'high': ticker.get('high', 0) or 0,
            'low': ticker.get('low', 0) or 0,
            'close': ticker.get('close', 0) or 0,
            'change_24h': ticker.get('percentage', 0) or 0
        }
    except:
        return None

# =========================================================
# ⭐ تقييم نتيجة الصفقة
# =========================================================
def evaluate_trade_outcome(entry_price, highest_price, lowest_price, current_price):
    """
    تقييم نتيجة الصفقة بناءً على أيهما تحقق أولاً: +6% أم -3%
    """
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
# ⭐ نظام تتبع العملات المرشحة
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
                    'Scan Time', 'Symbol', 'Rank', 'Entry Price', 'Current Price', 'Change %',
                    'Highest Price', 'Lowest Price', 'Stop Loss', 'Take Profit', 'Target %', 'Alpha',
                    'Status', 'Close Time', 'Evaluation', 'Virtual PNL %'
                ])

    def add_candidates(self, candidates_list, scan_time):
        """إضافة عملات مرشحة جديدة للمراقبة"""
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
                'status': 'ACTIVE',
                'close_time': None,
                'evaluation': 'PENDING',
                'virtual_pnl': 0
            }
            self.active_candidates.append(record)
            self._write_record(record)
    
    def update_prices(self, exchange_sync):
        """تحديث أسعار جميع العملات النشطة"""
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
                    
                    # تحديث أعلى وأدنى سعر
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
        """تقييم العملات النشطة وإغلاق منتهية الصلاحية أو المحققة للشروط"""
        now = datetime.now()
        
        for cand in self.active_candidates:
            if cand['status'] != 'ACTIVE':
                continue
            
            # تقييم النتيجة
            evaluation, pnl = evaluate_trade_outcome(
                cand['entry_price'],
                cand['highest_price'],
                cand['lowest_price'],
                cand['current_price']
            )
            
            age = (now - cand['scan_time']).total_seconds() / 3600
            
            # شروط الإغلاق
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
                print(f"⏰ {cand['symbol']} انتهت صلاحيتها بعد {MAX_AGE_HOURS} ساعة")
            
            else:
                # تحديث دوري للسجلات النشطة
                cand['evaluation'] = 'PENDING'
                cand['virtual_pnl'] = cand['change_pct']
                self._write_record(cand)
        
        # إزالة السجلات المغلقة من القائمة النشطة
        self.active_candidates = [c for c in self.active_candidates if c['status'] == 'ACTIVE']
    
    def _write_record(self, record):
        """كتابة سجل في ملف CSV"""
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
                record['status'],
                record['close_time'].isoformat() if record['close_time'] else '',
                record['evaluation'],
                f"{record['virtual_pnl']:.2f}%"
            ])
    
    def get_statistics(self):
        """حساب إحصائيات أداء الترشيحات"""
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
            'success_rate': (len(success) / len(closed)) * 100 if len(closed) > 0 else 0,
            'avg_success_pnl': SUCCESS_THRESHOLD * 100,
            'avg_fail_pnl': FAIL_THRESHOLD * 100
        }

# =========================================================
# نظام التداول الورقي (مبسط)
# =========================================================
class PaperTrader:
    def __init__(self, initial_capital=1000):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions = []
        self.closed_trades = []
        self.trades_csv = "closed_trades.csv"
        self._init_csv()

    def _init_csv(self):
        if not os.path.exists(self.trades_csv):
            with open(self.trades_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Symbol', 'Entry Price', 'Exit Price', 'Amount', 'PNL ($)', 'PNL (%)', 'Exit Reason'])

    def open_position(self, signal, exchange):
        """فتح صفقة حقيقية (افتراضية)"""
        symbol = signal['symbol']
        entry_price = signal['current_price']
        target_pct = signal.get('target_pct', 10)
        
        # حساب وقف الخسارة والهدف
        stop_loss = entry_price * (1 + FAIL_THRESHOLD)  # -3%
        take_profit = entry_price * (1 + SUCCESS_THRESHOLD)  # +6%
        
        # حجم الصفقة (10% من رأس المال)
        position_value = self.cash * 0.1
        amount = position_value / entry_price
        
        if position_value > self.cash:
            return False
        
        self.cash -= position_value
        position = {
            'symbol': symbol,
            'entry_price': entry_price,
            'amount': amount,
            'position_value': position_value,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'entry_time': datetime.now()
        }
        self.positions.append(position)
        
        msg = f"🟢 صفقة جديدة: {symbol}\nسعر الدخول: {entry_price:.4f}\nقيمة: {position_value:.2f}$\nالرصيد: {self.cash:.2f}$"
        print(msg)
        asyncio.create_task(send_telegram_message(msg))
        return True

    def update_positions(self, current_prices):
        """تحديث وإغلاق الصفقات المفتوحة"""
        to_close = []
        for i, pos in enumerate(self.positions):
            symbol = pos['symbol']
            if symbol not in current_prices:
                continue
            price = current_prices[symbol]
            
            if price <= pos['stop_loss']:
                to_close.append((i, price, "وقف خسارة"))
            elif price >= pos['take_profit']:
                to_close.append((i, price, "جني أرباح"))
        
        for i, price, reason in sorted(to_close, key=lambda x: x[0], reverse=True):
            self.close_position(i, price, reason)

    def close_position(self, index, exit_price, reason):
        """إغلاق صفقة"""
        pos = self.positions.pop(index)
        exit_value = pos['amount'] * exit_price
        pnl = exit_value - pos['position_value']
        pnl_pct = (pnl / pos['position_value']) * 100
        self.cash += exit_value
        
        trade = {
            'symbol': pos['symbol'],
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'amount': pos['amount'],
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'exit_reason': reason
        }
        self.closed_trades.append(trade)
        
        with open(self.trades_csv, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                trade['symbol'], f"{trade['entry_price']:.4f}", f"{trade['exit_price']:.4f}",
                f"{trade['amount']:.4f}", f"{trade['pnl']:.2f}", f"{trade['pnl_pct']:.2f}%", trade['exit_reason']
            ])
        
        msg = f"🔴 إغلاق {pos['symbol']}: {reason} | ربح = {pnl:.2f}$ ({pnl_pct:.2f}%) | الرصيد = {self.cash:.2f}$"
        print(msg)
        asyncio.create_task(send_telegram_message(msg))

# =========================================================
# دالة المسح والتحليل
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
    return score

async def scan_and_analyze(exchange_async, exchange_sync, symbols_to_scan):
    """مسح وتحليل مجموعة من العملات"""
    results = []
    for symbol in symbols_to_scan:
        try:
            ticker = await exchange_async.fetch_ticker(symbol)
            if not ticker or ticker.get('close', 0) <= 0:
                continue
            
            volatility = (ticker['high'] - ticker['low']) / ticker['close'] if ticker['close'] > 0 else 0
            volume_24h = ticker.get('quoteVolume', 0) or 0
            change_24h = ticker.get('percentage', 0) or 0
            
            if volume_24h < 200000 or volatility < 0.015 or change_24h > 50:
                continue
            
            df = fetch_ohlcv_sync(exchange_sync, symbol, '5m', 40)
            if df.empty:
                continue
            
            fs = calculate_filter_score(df)
            if fs < 15:  # ⭐ تخفيف
                continue
            
            results.append({
                'symbol': symbol,
                'entry_price': ticker['close'],
                'filter_score': fs,
                'target_pct': 15,  # قيمة افتراضية
                'alpha': fs / 40  # تقدير مبسط
            })
        except:
            continue
    
    results.sort(key=lambda x: x['filter_score'], reverse=True)
    return results[:TOP_CANDIDATES_COUNT]

# =========================================================
# حلقة التداول الرئيسية
# =========================================================
async def trading_loop():
    global all_symbols

    exchange_async = ccxt_async.gateio({'enableRateLimit': True})
    exchange_sync = ccxt.gateio({'enableRateLimit': True})

    markets = await exchange_async.load_markets()
    all_symbols = [s for s in markets if s.endswith('/USDT') and '.d' not in s]
    print(f"📋 تم تحميل {len(all_symbols)} عملة")

    trader = PaperTrader(initial_capital=INITIAL_CAPITAL)
    tracker = CandidateTracker()

    last_scan_time = 0
    last_price_update = 0
    
    print(f"🤖 بدء نظام تتبع العملات - {datetime.now()}\n")
    await send_telegram_message("🚀 نظام تتبع العملات المرشحة بدأ العمل!")

    while True:
        try:
            current_time = time.time()
            
            # ⭐ تحديث الأسعار كل دقيقة
            if current_time - last_price_update >= PRICE_UPDATE_INTERVAL:
                tracker.update_prices(exchange_sync)
                tracker.evaluate_and_close()
                
                # تحديث الصفقات المفتوحة
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
            
            # ⭐ مسح وتحليل كل 30 دقيقة
            if current_time - last_scan_time >= SCAN_INTERVAL:
                # اختيار 500 عملة للمسح
                start_idx = (current_time // SCAN_INTERVAL) % 2 * SYMBOLS_PER_CYCLE
                symbols_to_scan = all_symbols[start_idx:start_idx + SYMBOLS_PER_CYCLE]
                
                print(f"\n🔍 بدء مسح {len(symbols_to_scan)} عملة...")
                candidates = await scan_and_analyze(exchange_async, exchange_sync, symbols_to_scan)
                
                if candidates:
                    tracker.add_candidates(candidates, datetime.now())
                    print(f"✅ تم اكتشاف {len(candidates)} عملة مرشحة")
                    
                    # فتح صفقة على أفضل مرشح إذا توفر رصيد
                    if trader.cash > 50 and len(trader.positions) < 5:
                        best = candidates[0]
                        best['current_price'] = best['entry_price']
                        trader.open_position(best, exchange_sync)
                
                last_scan_time = current_time
                
                # عرض إحصائيات التتبع
                stats = tracker.get_statistics()
                if stats:
                    msg = f"📊 إحصائيات الترشيحات:\n"
                    msg += f"✅ نجاح: {stats['success']} | ❌ فشل: {stats['fail']}\n"
                    msg += f"🎯 نسبة النجاح: {stats['success_rate']:.1f}%"
                    print(msg)
            
            await asyncio.sleep(10)  # فحص كل 10 ثواني
            
        except KeyboardInterrupt:
            print("\n👋 إيقاف...")
            await send_telegram_message("⏹️ تم إيقاف النظام.")
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

if __name__ == "__main__":
    asyncio.run(main())
