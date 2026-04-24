#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚂 نظام اكتشاف الانفجارات - الإصدار الذهبي لمنصة Binance
First Station Explosion Detector - Binance Gold Edition

الإعدادات المثلى:
✅ منصة Binance (معدل طلبات آمن)
✅ أفضل 3 أنماط فقط (حيتان، هدوء، بولنجر)
✅ ثقة عالية (75%) ونمطين على الأقل
✅ سيولة مرتفعة (150,000$)
✅ جني أرباح 3.2% | وقف خسارة -2.0%
✅ وقف متحرك ذكي
✅ إشعارات تليجرام كاملة
✅ أوامر تفاعلية (/open, /closed, /stats, /download, /status)
✅ تسجيل في CSV وقاعدة بيانات SQLite
✅ لوحة تحكم ويب
✅ نبضات قلب كل ساعتين + تقرير يومي
"""

import asyncio, threading, sqlite3, pandas as pd, numpy as np, httpx, json, os, time, csv
from datetime import datetime, timedelta
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum

from flask import Flask, jsonify, render_template_string, send_file
import ccxt.async_support as ccxt_async

# =========================================================
# إعدادات تليجرام
# =========================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "5067771509")
BOT_TAG = "#BinanceBot"

# =========================================================
# 🏆 الإعدادات المثلى للتداول الحقيقي على Binance
# =========================================================
MAX_TRADES_PER_DAY = 5                      # 5 صفقات يومياً فقط
MAX_CONCURRENT_TRADES = 2                   # صفقتين متزامنتين كحد أقصى
TOTAL_CAPITAL = 1000.0
BASE_CAPITAL_PER_TRADE = 100.0
MAX_CAPITAL_PER_TRADE = 150.0
MIN_CAPITAL_PER_TRADE = 50.0

SCAN_INTERVAL = 45                          # مسح كل 45 ثانية
SCAN_BATCH_SIZE = 50
SCAN_SYMBOLS_LIMIT = 200                    # 200 عملة (مناسب لبينانس)

# 🎯 إعدادات الجودة العالية
MIN_CONFIDENCE = 75                         # فقط الإشارات القوية
MIN_PATTERNS_REQUIRED = 2                   # نمطان على الأقل
MIN_VOLUME_24H = 150000                     # سيولة مرتفعة
MAX_SPREAD = 0.2                            # سبريد ضيق
MAX_PRICE_CHANGE_24H = 7.0                  # العملة لم تتحرك كثيراً

# 🎯 أفضل 3 أنماط فقط (استبعاد الأنماط الضعيفة)
ALLOWED_PATTERNS = ['whale_accumulation', 'calm_before_storm', 'bollinger_squeeze']

PATTERN_WEIGHTS = {
    'calm_before_storm': 45,
    'whale_accumulation': 55,                # الأعلى وزناً
    'bollinger_squeeze': 40
}

# 🎯 شروط السوق
BTC_MIN_ADX = 22
BTC_MAX_DROP_1H = -1.5

# تعطيل Micro Pump (Binance ليس لديها عملات رخيصة جداً)
ENABLE_MICRO_PUMP_MODE = False

# =========================================================
# 🎯 استراتيجية الخروج المثلى
# =========================================================
EXIT_STRATEGY = {
    'take_profit': 3.2,                      # جني أرباح 3.2%
    'hard_stop_loss': -2.0,                  # وقف خسارة -2.0%
    'trailing_stop': {
        'activation': 2.0,                   # تفعيل بعد +2%
        'distance': 1.0                      # مسافة 1%
    }
}

# =========================================================
# 🎯 إعدادات الخروج المبكر
# =========================================================
ENABLE_EARLY_EXIT = True
EARLY_EXIT_BEARISH_CANDLE_BODY = 1.0         # شمعة هبوط 1%
EARLY_EXIT_EMA_FAST = 9
EARLY_EXIT_EMA_SLOW = 21
EARLY_EXIT_BREAK_PREV_LOW = True

# =========================================================
# إعدادات الملفات وقاعدة البيانات
# =========================================================
LOG_DIR = "trading_logs"
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(f"{LOG_DIR}/daily", exist_ok=True)
SIGNALS_FILE = f"{LOG_DIR}/signals_detected.csv"
TRADES_FILE = f"{LOG_DIR}/trades_executed.csv"
SNAPSHOT_FILE = f"{LOG_DIR}/market_snapshots.csv"
ERRORS_FILE = f"{LOG_DIR}/errors_log.csv"
DB_FILE = f"{LOG_DIR}/bot_state.db"

def init_database():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS bot_status
                 (id INTEGER PRIMARY KEY, capital REAL, available REAL, active_trades INTEGER,
                  daily_trades INTEGER, win_rate REAL, market_regime TEXT, btc_change REAL, last_update TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS trades_archive
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, entry_price REAL, exit_price REAL,
                  pnl_pct REAL, pnl_usd REAL, entry_time TEXT, exit_time TEXT, pattern TEXT, status TEXT)''')
    conn.commit()
    conn.close()

def update_db_status(capital, available, active, daily, win_rate, regime, btc_change):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM bot_status")
    c.execute('''INSERT INTO bot_status 
                 (capital, available, active_trades, daily_trades, win_rate, market_regime, btc_change, last_update)
                 VALUES (?,?,?,?,?,?,?,?)''',
              (capital, available, active, daily, win_rate, regime, btc_change, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def insert_trade_archive(symbol, entry_price, exit_price, pnl_pct, pnl_usd, entry_time, exit_time, pattern, status):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT INTO trades_archive 
                 (symbol, entry_price, exit_price, pnl_pct, pnl_usd, entry_time, exit_time, pattern, status)
                 VALUES (?,?,?,?,?,?,?,?,?)''',
              (symbol, entry_price, exit_price, pnl_pct, pnl_usd, entry_time, exit_time, pattern, status))
    conn.commit()
    conn.close()

# =========================================================
# أنواع البيانات
# =========================================================
class MarketRegime(Enum):
    TRENDING_BULLISH = "trending_bullish"; TRENDING_BEARISH = "trending_bearish"
    RANGING = "ranging"; TRANSITIONAL = "transitional"

@dataclass
class ExplosionSignal:
    symbol: str; confidence: float; expected_move: float; time_to_explosion: int
    entry_price: float; patterns: List[str]; volume_24h: float
    current_change: float; priority: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    atr_percent: float = 0.0
    def get_time_estimate(self) -> str:
        m, s = divmod(self.time_to_explosion, 60)
        return f"{m} دقيقة و {s} ثانية" if m else f"{s} ثانية"

@dataclass
class ActiveTrade:
    symbol: str; entry_price: float; capital: float; quantity: float
    remaining_quantity: float; entry_time: datetime; highest_price: float
    trailing_stop: float; trailing_activated: bool; take_profits_hit: bool
    pattern: str; confidence: float; atr_percent: float = 0.0

# =========================================================
# مدير الصفقات (مع استراتيجية الخروج المثلى)
# =========================================================
class TradeManager:
    def __init__(self, notifier=None):
        self.active_trades: Dict[str, ActiveTrade] = {}
        self.closed_trades: List[dict] = []
        self.available_capital = TOTAL_CAPITAL
        self.daily_trades = 0; self.daily_pnl = 0.0; self.total_trades = 0; self.winning_trades = 0
        self.notifier = notifier

    def open_trade(self, signal: ExplosionSignal) -> Tuple[bool, float]:
        symbol = signal.symbol
        if symbol in self.active_trades: return False, 0.0
        if len(self.active_trades) >= MAX_CONCURRENT_TRADES: return False, 0.0
        if self.daily_trades >= MAX_TRADES_PER_DAY: return False, 0.0
        
        # حجم الصفقة يعتمد على الثقة
        if signal.confidence >= 85: capital = MAX_CAPITAL_PER_TRADE
        elif signal.confidence >= 78: capital = BASE_CAPITAL_PER_TRADE
        else: capital = MIN_CAPITAL_PER_TRADE
        
        if capital > self.available_capital: return False, 0.0
        quantity = capital / signal.entry_price
        self.available_capital -= capital
        self.daily_trades += 1; self.total_trades += 1
        trade = ActiveTrade(symbol=symbol, entry_price=signal.entry_price, capital=capital,
                            quantity=quantity, remaining_quantity=quantity,
                            entry_time=datetime.now(), highest_price=signal.entry_price,
                            trailing_stop=0, trailing_activated=False, take_profits_hit=False,
                            pattern=signal.patterns[0] if signal.patterns else 'unknown',
                            confidence=signal.confidence, atr_percent=signal.atr_percent)
        self.active_trades[symbol] = trade
        print(f"  ✅ {symbol}: دخول ناجح! الثقة={signal.confidence:.0f}% | المبلغ={capital:.1f}$")
        return True, capital

    def update_trade(self, symbol: str, current_price: float, ohlcv_5m: Optional[np.ndarray] = None) -> Optional[dict]:
        if symbol not in self.active_trades: return None
        trade = self.active_trades[symbol]
        if current_price > trade.highest_price: trade.highest_price = current_price
        pnl_pct = (current_price - trade.entry_price) / trade.entry_price * 100

        # وقف الخسارة الثابت
        if pnl_pct <= EXIT_STRATEGY['hard_stop_loss']:
            return self._close_trade(symbol, current_price, pnl_pct, 'stop_loss')

        # جني الأرباح
        if not trade.take_profits_hit and pnl_pct >= EXIT_STRATEGY['take_profit']:
            trade.take_profits_hit = True
            return self._close_trade(symbol, current_price, pnl_pct, 'take_profit')

        # وقف متحرك
        if pnl_pct >= EXIT_STRATEGY['trailing_stop']['activation']:
            trailing_dist = EXIT_STRATEGY['trailing_stop']['distance']
            new_stop = trade.highest_price * (1 - trailing_dist/100)
            if not trade.trailing_activated:
                trade.trailing_activated = True
                trade.trailing_stop = new_stop
            elif new_stop > trade.trailing_stop:
                trade.trailing_stop = new_stop
            if trade.trailing_activated and current_price <= trade.trailing_stop:
                return self._close_trade(symbol, current_price, pnl_pct, 'trailing_stop')

        # خروج مبكر
        if ENABLE_EARLY_EXIT and ohlcv_5m is not None and len(ohlcv_5m) >= 10 and pnl_pct > 0:
            closes_5m = ohlcv_5m[:, 4]; opens_5m = ohlcv_5m[:, 1]; lows_5m = ohlcv_5m[:, 3]
            body = closes_5m[-1] - opens_5m[-1]
            body_pct = abs(body) / opens_5m[-1] * 100
            if body < 0 and body_pct >= EARLY_EXIT_BEARISH_CANDLE_BODY:
                return self._close_trade(symbol, current_price, pnl_pct, 'early_exit_bearish_candle')
            ema9 = pd.Series(closes_5m).ewm(span=EARLY_EXIT_EMA_FAST, adjust=False).mean().values
            ema21 = pd.Series(closes_5m).ewm(span=EARLY_EXIT_EMA_SLOW, adjust=False).mean().values
            if len(ema9) > 1 and ema9[-2] >= ema21[-2] and ema9[-1] < ema21[-1]:
                return self._close_trade(symbol, current_price, pnl_pct, 'early_exit_ema_cross')
            if EARLY_EXIT_BREAK_PREV_LOW and len(lows_5m) >= 6:
                prev_low = np.min(lows_5m[-6:-1])
                if current_price < prev_low:
                    return self._close_trade(symbol, current_price, pnl_pct, 'early_exit_break_low')

        return None

    def _close_trade(self, symbol: str, price: float, pnl_pct: float, reason: str) -> dict:
        trade = self.active_trades[symbol]
        if trade.remaining_quantity > 0:
            self.available_capital += trade.remaining_quantity * price
        pnl_usd = trade.capital * pnl_pct / 100
        self.daily_pnl += pnl_pct
        if pnl_pct > 0: self.winning_trades += 1
        result = {'symbol': symbol, 'entry_price': trade.entry_price, 'exit_price': price,
                  'pnl_pct': pnl_pct, 'pnl_usd': pnl_usd, 'entry_time': trade.entry_time,
                  'exit_time': datetime.now(), 'pattern': trade.pattern,
                  'confidence': trade.confidence, 'exit_reason': reason,
                  'take_profits_hit': trade.take_profits_hit, 'capital_allocated': trade.capital}
        self.closed_trades.append(result)
        try:
            insert_trade_archive(symbol, trade.entry_price, price, pnl_pct, pnl_usd,
                                trade.entry_time.isoformat(), datetime.now().isoformat(),
                                trade.pattern, 'closed')
        except Exception as e:
            print(f"  ⚠️ خطأ في تسجيل الصفقة في DB: {e}")
        del self.active_trades[symbol]
        print(f"  🏁 {symbol}: {pnl_pct:+.2f}% | {reason} | متاح: {self.available_capital:.2f}$")
        if self.notifier:
            asyncio.create_task(self.notifier.send_trade_closed_alert(result, self.available_capital))
        return result

    def get_win_rate(self) -> float:
        return (self.winning_trades / self.total_trades * 100) if self.total_trades else 0.0

# =========================================================
# كاشف الانفجارات (مع حساب نسبة الارتفاع المتوقعة)
# =========================================================
class ExplosionDetector:
    def __init__(self):
        self.pattern_weights = PATTERN_WEIGHTS
        self.recent_signals = deque(maxlen=100)
        self.last_signal_time = {}
    EXCLUDED_PATTERNS = ['3S', '3L', '5S', '5L', 'X3', 'X5', 'BEAR', 'BULL', 'UP', 'DOWN']
    EXCLUDED_SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT']

    async def scan_market(self, exchange) -> List[ExplosionSignal]:
        print(f"\n{'='*60}\n🔍 مسح السوق - {datetime.now().strftime('%H:%M:%S')}\n{'='*60}")
        symbols = await self._get_active_symbols(exchange)
        print(f"📊 جاري فحص {len(symbols)} عملة...")
        all_signals = []
        for i in range(0, len(symbols), SCAN_BATCH_SIZE):
            batch = symbols[i:i+SCAN_BATCH_SIZE]
            tasks = [self._analyze_symbol(exchange, sym) for sym in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, ExplosionSignal) and self._should_accept_signal(result):
                    all_signals.append(result)
                    self._record_signal(result)
            print(f"   📊 تقدم: {min(i+SCAN_BATCH_SIZE, len(symbols))}/{len(symbols)}")
            await asyncio.sleep(0.2)
        all_signals.sort(key=lambda x: (x.priority, x.confidence), reverse=True)
        return all_signals

    async def _get_active_symbols(self, exchange) -> List[str]:
        try:
            tickers = await exchange.fetch_tickers()
            active = []
            if not tickers: return active
            for sym, ticker in tickers.items():
                if not sym or not sym.endswith('/USDT'): continue
                base = sym.split('/')[0]
                if base in self.EXCLUDED_SYMBOLS: continue
                if any(p in base for p in self.EXCLUDED_PATTERNS): continue
                vol = ticker.get('quoteVolume') or 0.0
                ch = ticker.get('percentage') or 0.0
                bid = ticker.get('bid') or 0.0; ask = ticker.get('ask') or 0.0
                price = ticker.get('last') or 0.0
                if price <= 0: continue
                if vol < MIN_VOLUME_24H: continue
                if ch > MAX_PRICE_CHANGE_24H or ch < -15: continue
                if bid > 0 and ask > 0 and (ask - bid) / bid * 100 > MAX_SPREAD: continue
                active.append(sym)
            active.sort(key=lambda s: tickers.get(s, {}).get('quoteVolume') or 0.0, reverse=True)
            return active[:SCAN_SYMBOLS_LIMIT]
        except Exception as e:
            print(f"⚠️ خطأ في جلب العملات: {e}")
            return []

    async def _analyze_symbol(self, exchange, symbol: str) -> Optional[ExplosionSignal]:
        try:
            ohlcv_1m = await exchange.fetch_ohlcv(symbol, '1m', limit=60)
            ohlcv_5m = await exchange.fetch_ohlcv(symbol, '5m', limit=30)
            ticker = await exchange.fetch_ticker(symbol)
            if len(ohlcv_1m) < 30 or len(ohlcv_5m) < 20: return None
            data_1m = np.array(ohlcv_1m); data_5m = np.array(ohlcv_5m)
            closes_1m, volumes_1m = data_1m[:,4], data_1m[:,5]
            closes_5m, volumes_5m = data_5m[:,4], data_5m[:,5]
            highs_5m, lows_5m = data_5m[:,2], data_5m[:,3]
            current_price = ticker['last']
            atr = np.mean(highs_5m[-14:] - lows_5m[-14:]) if len(highs_5m) >= 14 else 0
            atr_percent = (atr / current_price * 100) if current_price > 0 else 2.0
            
            detected_patterns = []; total_conf = 0; time_w = 0; time_exp = 0
            
            checks = []
            if 'calm_before_storm' in ALLOWED_PATTERNS:
                checks.append(self._check_calm_before_storm(volumes_5m, closes_5m))
            if 'whale_accumulation' in ALLOWED_PATTERNS:
                checks.append(self._check_whale_accumulation(volumes_1m, closes_1m))
            if 'bollinger_squeeze' in ALLOWED_PATTERNS:
                checks.append(self._check_bollinger_squeeze(closes_5m))
                
            for check in checks:
                if check['detected']:
                    detected_patterns.append(check['name'])
                    w = self.pattern_weights.get(check.get('pattern_name', ''), 20)
                    total_conf += w; time_exp += check['time_estimate'] * w; time_w += w
            
            if total_conf >= MIN_CONFIDENCE and len(detected_patterns) >= MIN_PATTERNS_REQUIRED:
                avg_time = int(time_exp / time_w) if time_w else 180
                expected_move = self._calculate_expected_move(total_conf, len(detected_patterns))
                priority = self._calculate_priority(total_conf, len(detected_patterns), avg_time)
                
                # 🆕 حساب نقطة الدخول المثالية
                optimal_entry = self._calculate_optimal_entry(closes_5m, current_price)
                
                return ExplosionSignal(symbol=symbol, confidence=min(100, total_conf),
                    expected_move=expected_move, time_to_explosion=avg_time,
                    entry_price=optimal_entry, patterns=detected_patterns,
                    volume_24h=ticker.get('quoteVolume',0),
                    current_change=ticker.get('percentage',0),
                    priority=priority, atr_percent=round(atr_percent,2))
        except: return None
        return None

    def _calculate_optimal_entry(self, closes, current_price):
        """حساب أفضل نقطة دخول بناءً على آخر 10 شمعات"""
        recent_low = np.min(closes[-10:])
        recent_high = np.max(closes[-5:])
        # نقطة الدخول المثالية = منتصف النطاق السعري الأخير
        optimal = (recent_low + recent_high) / 2
        # إذا كان السعر الحالي أقل من المثالي، نستخدم السعر الحالي (فرصة أفضل)
        if current_price <= optimal:
            return current_price
        # وإلا ننتظر تراجعاً طفيفاً (نقطة وسط بين الحالي والمثالي)
        return (current_price + optimal) / 2

    def _check_calm_before_storm(self, volumes, closes):
        if len(volumes)<15 or len(closes)<10: return {'detected':False}
        r = np.mean(volumes[-5:])/np.mean(volumes[-15:-5]) if np.mean(volumes[-15:-5])>0 else 1
        pr = (np.max(closes[-8:])-np.min(closes[-8:]))/np.mean(closes[-8:])*100
        if r<0.5 and pr<2.0: return {'detected':True, 'name':'🌊 هدوء','time_estimate':300,'pattern_name':'calm_before_storm'}
        return {'detected':False}

    def _check_whale_accumulation(self, volumes, closes):
        if len(volumes)<10 or len(closes)<5: return {'detected':False}
        r = volumes[-1]/np.mean(volumes[-10:]) if np.mean(volumes[-10:])>0 else 1
        st = (np.max(closes[-5:])-np.min(closes[-5:]))/np.mean(closes[-5:])*100
        if r>1.5 and st<1.5: return {'detected':True, 'name':f'🐋 حيتان ({r:.1f}x)','time_estimate':180,'pattern_name':'whale_accumulation'}
        return {'detected':False}

    def _check_bollinger_squeeze(self, closes):
        if len(closes)<20: return {'detected':False}
        recent=closes[-20:]; cur=closes[-1]; mid=np.mean(recent); std=np.std(recent)
        upper=mid+2*std; lower=mid-2*std; bw=(upper-lower)/mid*100
        pos=(cur-lower)/(upper-lower) if upper!=lower else 0.5
        if bw<5.0 and pos<0.4: return {'detected':True, 'name':f'🎯 بولنجر ({bw:.1f}%)','time_estimate':240,'pattern_name':'bollinger_squeeze'}
        return {'detected':False}

    def _calculate_expected_move(self, conf, cnt):
        """حساب نسبة الارتفاع المتوقعة"""
        base = EXIT_STRATEGY['take_profit']  # 3.2%
        if cnt >= 3: base += 2.0              # +2% إذا 3 أنماط
        elif cnt >= 2: base += 1.0            # +1% إذا نمطان
        if conf >= 85: base += 1.5            # +1.5% إذا ثقة عالية جداً
        elif conf >= 78: base += 0.8          # +0.8% إذا ثقة جيدة
        return round(base, 1)

    def _calculate_priority(self, conf, cnt, time_sec):
        pri = 2 if conf >= MIN_CONFIDENCE else 1
        if conf >= 85: pri += 1
        if cnt >= 3: pri += 1
        if time_sec < 120: pri += 1
        return min(5, pri)

    def _should_accept_signal(self, signal):
        now=datetime.now()
        if signal.symbol in self.last_signal_time and (now-self.last_signal_time[signal.symbol]).total_seconds()<300: return False
        return True

    def _record_signal(self, signal): self.recent_signals.append(signal); self.last_signal_time[signal.symbol]=datetime.now()

# =========================================================
# نظام الإشعارات (موثوق)
# =========================================================
class EnhancedExplosionNotifier:
    def __init__(self):
        self.telegram_token = TELEGRAM_TOKEN; self.telegram_chat_id = TELEGRAM_CHAT_ID

    async def send_open_trade_alert(self, signal, capital):
        pat="\n".join(f"  • {p}" for p in signal.patterns)
        msg=f"""🔴 *فتح صفقة جديدة*\n{BOT_TAG}\n\n🪙 *{signal.symbol}*\n💵 السعر: {signal.entry_price:.8f}\n💰 المبلغ: {capital:.2f}$\n📊 الثقة: {signal.confidence:.1f}%\n📈 الارتفاع المتوقع: +{signal.expected_move:.1f}%\n🎯 الأولوية: {signal.priority}/5\n📋 الأنماط:\n{pat}\n🕐 `{datetime.now().strftime('%H:%M:%S')}`"""
        await self._send_telegram(msg)

    async def send_trade_closed_alert(self, result, available):
        emoji="💰" if result['pnl_pct']>0 else "📉"
        msg=f"""{emoji} *إغلاق صفقة*\n{BOT_TAG}\n\n🪙 {result['symbol']}\n📊 الربح: {result['pnl_pct']:+.2f}% ({result['pnl_usd']:+.2f}$)\n🎯 السبب: {result['exit_reason']}\n💵 الرصيد الحالي: {available:.2f}$\n🕐 `{datetime.now().strftime('%H:%M:%S')}`"""
        await self._send_telegram(msg)

    async def send_startup_message(self):
        msg=f"""🚀 *تم تشغيل نظام الانفجارات - Binance*\n{BOT_TAG}\n⚙️ جني أرباح: {EXIT_STRATEGY['take_profit']}% | وقف خسارة: {EXIT_STRATEGY['hard_stop_loss']}%\n🎯 ثقة: {MIN_CONFIDENCE}% | أنماط: {MIN_PATTERNS_REQUIRED}\n💰 رأس المال: {TOTAL_CAPITAL}$\n✅ *النظام يعمل بنجاح!*\n🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"""
        await self._send_telegram(msg)

    async def send_daily_report(self, tm):
        wr=tm.get_win_rate(); net=tm.available_capital-TOTAL_CAPITAL
        msg=f"""📊 *التقرير اليومي*\n{BOT_TAG}\n🔄 صفقات اليوم: {tm.daily_trades}\n✅ نسبة النجاح: {wr:.1f}%\n💰 صافي الربح: {net:+.2f}$\n🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"""
        await self._send_telegram(msg)

    async def send_heartbeat(self, engine):
        m=engine.market_regime
        msg=f"""💓 *نبضة قلب*\n{BOT_TAG}\n📊 السوق: {m.get('regime','?')}\n🔍 دورات: {engine.scan_count}\n📈 صفقات اليوم: {engine.trade_manager.daily_trades}\n🎯 نجاح: {engine.trade_manager.get_win_rate():.1f}%\n🕐 `{datetime.now().strftime('%H:%M:%S')}`"""
        await self._send_telegram(msg)

    async def send_csv_links(self, chat_id):
        base=os.environ.get("RENDER_EXTERNAL_URL","http://localhost:8080")
        msg=f"""📁 *روابط تحميل CSV*\n{BOT_TAG}\n• [الإشارات]({base}/download/signals)\n• [الصفقات]({base}/download/trades)\n• [اللقطات]({base}/download/snapshots)\n• [الأخطاء]({base}/download/errors)"""
        await self._send_telegram_to_chat(chat_id, msg)

    async def _send_telegram(self, message):
        await self._send_telegram_to_chat(self.telegram_chat_id, message)

    async def _send_telegram_to_chat(self, chat_id, message):
        try:
            url=f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json={"chat_id":chat_id,"text":message.strip(),"parse_mode":"Markdown"})
        except Exception as e: print(f"⚠️ خطأ تليجرام: {e}")

# =========================================================
# مستمع أوامر تليجرام
# =========================================================
class TelegramPoller:
    def __init__(self, token, engine, notifier):
        self.token = token; self.engine = engine; self.notifier = notifier
        self.last_update_id = 0

    async def start(self):
        print("🤖 بدء استقبال أوامر تليجرام...")
        try:
            url = f"https://api.telegram.org/bot{self.token}/getUpdates"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params={"offset": -1, "timeout": 2})
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok") and data["result"]:
                        self.last_update_id = data["result"][-1]["update_id"] + 1
        except Exception: pass

        while True:
            try:
                url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                params = {"offset": self.last_update_id + 1, "timeout": 10}
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(url, params=params)
                data = resp.json()
                if data.get("ok"):
                    for upd in data["result"]:
                        self.last_update_id = upd["update_id"]
                        message = upd.get("message")
                        if message and "text" in message:
                            text = message["text"].strip(); chat_id = message["chat"]["id"]
                            if text == "/status": await self._reply_status(chat_id)
                            elif text == "/download": await self.notifier.send_csv_links(chat_id)
                            elif text == "/open": await self._reply_open(chat_id)
                            elif text == "/closed": await self._reply_closed(chat_id)
                            elif text == "/stats": await self._reply_stats(chat_id)
                            elif text == "/help": await self._reply_help(chat_id)
                            else: await self._send_msg(chat_id, "❌ أمر غير معروف. استخدم /help")
            except Exception as e: print(f"⚠️ خطأ في poller: {e}")
            await asyncio.sleep(1)

    async def _reply_status(self, chat_id):
        e=self.engine
        msg=f"""📊 *حالة البوت*\n{BOT_TAG}\n🔍 دورات: {e.scan_count}\n💵 الرصيد: {e.trade_manager.available_capital:.2f}$\n📊 نشطة: {len(e.trade_manager.active_trades)}\n📈 اليوم: {e.trade_manager.daily_trades}\n🎯 نجاح: {e.trade_manager.get_win_rate():.1f}%\n🕐 `{datetime.now().strftime('%H:%M:%S')}`"""
        await self._send_msg(chat_id, msg)

    async def _reply_open(self, chat_id):
        active=self.engine.trade_manager.active_trades
        if not active: await self._send_msg(chat_id,"📊 لا توجد صفقات مفتوحة."); return
        msg=f"📊 *الصفقات المفتوحة ({len(active)})*\n{BOT_TAG}\n"
        for sym,trade in active.items():
            pnl=(trade.highest_price-trade.entry_price)/trade.entry_price*100
            d=datetime.now()-trade.entry_time; h,r=divmod(int(d.total_seconds()),3600); m=r//60
            emoji="🟢" if pnl>0 else "🔴"
            msg+=f"\n{emoji} *{sym}*\n   💵 الدخول: {trade.entry_price:.8f}\n   📈 الحالي: {trade.highest_price:.8f}\n   📊 الربح: {pnl:+.2f}%\n   ⏱️ المدة: {h}h {m}m\n"
        await self._send_msg(chat_id, msg.strip())

    async def _reply_closed(self, chat_id):
        closed=self.engine.trade_manager.closed_trades[-10:]
        if not closed: await self._send_msg(chat_id,"📊 لا توجد صفقات مغلقة."); return
        msg=f"📊 *آخر {len(closed)} صفقة مغلقة*\n{BOT_TAG}\n"
        for t in reversed(closed):
            emoji="💰" if t['pnl_pct']>0 else "📉"; d=t['exit_time']-t['entry_time']
            h,r=divmod(int(d.total_seconds()),3600); m=r//60
            msg+=f"\n{emoji} *{t['symbol']}*\n   📊 النتيجة: {t['pnl_pct']:+.2f}% ({t['pnl_usd']:+.2f}$)\n   🎯 النوع: {t['pattern']}\n   ⏱️ المدة: {h}h {m}m\n   🛑 السبب: {t['exit_reason']}\n"
        await self._send_msg(chat_id, msg.strip())

    async def _reply_stats(self, chat_id):
        tm=self.engine.trade_manager; total=tm.total_trades; wins=tm.winning_trades; losses=total-wins
        wr=tm.get_win_rate(); net=tm.available_capital-TOTAL_CAPITAL
        ps={}
        for t in tm.closed_trades:
            p=t.get('pattern','?')
            if p not in ps: ps[p]={'total':0,'wins':0,'pnl':0.0,'usd':0.0}
            ps[p]['total']+=1; ps[p]['pnl']+=t['pnl_pct']; ps[p]['usd']+=t['pnl_usd']
            if t['pnl_pct']>0: ps[p]['wins']+=1
        msg=f"""📊 *إحصائيات الأداء*\n{BOT_TAG}\n📈 *إجمالي:*\n🔄 الصفقات: {total}\n✅ الرابحة: {wins}\n❌ الخاسرة: {losses}\n🎯 نسبة النجاح: {wr:.1f}%\n💰 صافي الربح: {net:+.2f}$\n\n📋 *حسب النوع:*\n"""
        for p,s in ps.items():
            w=s['wins']/s['total']*100 if s['total']>0 else 0
            msg+=f"• {p}\n   الصفقات: {s['total']} | نجاح: {w:.0f}%\n   الربح: {s['pnl']:+.2f}% ({s['usd']:+.2f}$)\n"
        msg+=f"\n🕐 `{datetime.now().strftime('%H:%M:%S')}`"
        await self._send_msg(chat_id, msg.strip())

    async def _reply_help(self, chat_id):
        msg=f"""📋 *الأوامر المتاحة*\n{BOT_TAG}\n/status – حالة البوت\n/open – الصفقات المفتوحة\n/closed – آخر الصفقات المغلقة\n/stats – إحصائيات الأداء\n/download – تحميل ملفات CSV\n/help – هذه القائمة"""
        await self._send_msg(chat_id, msg)

    async def _send_msg(self, chat_id, text):
        try:
            url=f"https://api.telegram.org/bot{self.token}/sendMessage"
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json={"chat_id":chat_id,"text":text,"parse_mode":"Markdown"})
        except Exception as e: print(f"⚠️ فشل إرسال: {e}")

# =========================================================
# فلتر السوق
# =========================================================
class MarketRegimeFilter:
    def __init__(self): self.btc_symbol='BTC/USDT'; self.regime_data={}
    async def analyze(self, exchange) -> dict:
        try:
            ohlcv=await exchange.fetch_ohlcv(self.btc_symbol,'1h',limit=50)
            df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
            c,h,l=df['c'].values,df['h'].values,df['l'].values
            adx=self._calc_adx(h,l,c); ema20,ema50=self._ema(c,20),self._ema(c,50)
            trend="bullish" if ema20[-1]>ema50[-1] else "bearish"
            btc_change_1h=((c[-1]-c[-4])/c[-4])*100 if len(c)>=4 else 0
            can_trade = adx >= BTC_MIN_ADX and btc_change_1h > BTC_MAX_DROP_1H
            self.regime_data={'regime':'trending_bullish' if trend=='bullish' else 'trending_bearish','adx':round(adx,1),'btc_change_1h':round(btc_change_1h,2),'can_trade':can_trade,'trend':trend}
            return self.regime_data
        except: return {'can_trade':True,'trend':'unknown','adx':0,'btc_change_1h':0}
    def _calc_adx(self, h,l,c,p=14):
        if len(c)<p+1: return 20
        tr=np.maximum(np.maximum(h[1:]-l[1:],np.abs(h[1:]-c[:-1])),np.abs(l[1:]-c[:-1]))
        atr=np.mean(tr[-p:]) if len(tr)>=p else np.mean(tr)
        up,down=h[1:]-h[:-1],l[:-1]-l[1:]
        plus_dm=np.where((up>down)&(up>0),up,0); minus_dm=np.where((down>up)&(down>0),down,0)
        plus_di=100*np.mean(plus_dm[-p:])/atr if atr>0 else 0; minus_di=100*np.mean(minus_dm[-p:])/atr if atr>0 else 0
        dx=100*np.abs(plus_di-minus_di)/(plus_di+minus_di) if (plus_di+minus_di)>0 else 0
        return dx
    def _ema(self, data, p):
        alpha=2/(p+1); ema=np.zeros_like(data)
        if len(data)>=p:
            ema[p-1]=np.mean(data[:p])
            for i in range(p,len(data)): ema[i]=data[i]*alpha+ema[i-1]*(1-alpha)
        return ema

# =========================================================
# المحرك الرئيسي (مستقر مع Binance)
# =========================================================
class ExplosionScannerEngine:
    def __init__(self):
        self.notifier = EnhancedExplosionNotifier()
        self.detector = ExplosionDetector()
        self.market_filter = MarketRegimeFilter()
        self.trade_manager = TradeManager(notifier=self.notifier)
        self.scan_count = 0; self.total_signals = 0; self.market_regime = {}
        self.last_scan_stats = {'scanned':0,'signals':0,'duration':0,'time':'-'}
        self.last_daily_report = datetime.now(); self.last_heartbeat = datetime.now()

    async def run(self):
        global engine_instance; engine_instance = self
        print("╔══════════════════════════════════════════════════════════╗\n║     💥 نظام الانفجارات - Binance الذهبي 💥      ║\n╚══════════════════════════════════════════════════════════╝")
        
        while True:
            try:
                exchange = ccxt_async.binance({
                    'enableRateLimit': True,
                    'rateLimit': 200,
                    'options': {'defaultType': 'spot'}
                })
                await exchange.fetch_ticker('BTC/USDT')
                print("✅ تم الاتصال بـ Binance بنجاح.")
                break
            except Exception as e:
                print(f"❌ فشل الاتصال بـ Binance: {e}. إعادة المحاولة خلال 30 ثانية...")
                await asyncio.sleep(30)

        await self.notifier.send_startup_message()
        
        while True:
            try:
                self.scan_count += 1
                start_time = time.time()
                
                try: self.market_regime = await self.market_filter.analyze(exchange)
                except: self.market_regime = {'can_trade': True}

                if self.trade_manager.active_trades:
                    ohlcv_tasks = {s: exchange.fetch_ohlcv(s, '5m', limit=26) for s in self.trade_manager.active_trades}
                    ohlcv_results = {}
                    for sym, task in ohlcv_tasks.items():
                        try: ohlcv_results[sym] = await task
                        except: ohlcv_results[sym] = None
                    for symbol in list(self.trade_manager.active_trades.keys()):
                        try:
                            ticker = await exchange.fetch_ticker(symbol); price = ticker['last']
                            ohlcv_data = ohlcv_results.get(symbol)
                            if ohlcv_data and len(ohlcv_data) >= 26:
                                self.trade_manager.update_trade(symbol, price, np.array(ohlcv_data))
                            else:
                                self.trade_manager.update_trade(symbol, price)
                        except: pass

                signals = []
                if self.market_regime.get('can_trade', True):
                    try: signals = await self.detector.scan_market(exchange)
                    except: pass
                    if signals:
                        print(f"\n🎯 {len(signals)} إشارة!")
                        slots = MAX_CONCURRENT_TRADES - len(self.trade_manager.active_trades)
                        for signal in signals[:slots]:
                            if signal.priority >= 3:
                                success, capital = self.trade_manager.open_trade(signal)
                                if success:
                                    await self.notifier.send_open_trade_alert(signal, capital)
                                    self.total_signals += 1
                                    await asyncio.sleep(0.3)
                    else: print("\n⚪ لا توجد إشارات")
                else: print("\n⚠️ التداول متوقف - السوق غير مناسب")

                elapsed = time.time() - start_time
                self.last_scan_stats = {'scanned':SCAN_SYMBOLS_LIMIT,'signals':len(signals),'duration':round(elapsed,2),'time':datetime.now().strftime('%H:%M:%S')}

                if (datetime.now() - self.last_heartbeat).total_seconds() > 7200:
                    try: await self.notifier.send_heartbeat(self)
                    except: pass
                    self.last_heartbeat = datetime.now()
                
                now = datetime.now()
                if now.hour == 23 and now.minute >= 55 and (now - self.last_daily_report).total_seconds() > 3600:
                    try: await self.notifier.send_daily_report(self.trade_manager)
                    except: pass
                    self.last_daily_report = now
                
                print(f"\n📊 دورة #{self.scan_count} | ⏱️ {elapsed:.1f} ثانية | نشطة: {len(self.trade_manager.active_trades)}")
                
            except Exception as e:
                print(f"❌ خطأ غير متوقع في الدورة #{self.scan_count}: {e}")
                import traceback; traceback.print_exc()
            
            try: await asyncio.sleep(SCAN_INTERVAL)
            except asyncio.CancelledError: break

# =========================================================
# تطبيق Flask
# =========================================================
app = Flask(__name__)
engine_instance = None

@app.route('/')
def dashboard():
    if not engine_instance: return "Engine not started yet."
    m = engine_instance.market_regime; s = engine_instance.last_scan_stats; tm = engine_instance.trade_manager
    return render_template_string('''
    <!DOCTYPE html><html dir="rtl"><head><title>نظام الانفجارات - Binance</title><meta charset="utf-8"><meta http-equiv="refresh" content="30">
    <style>body{font-family:Arial;background:#1a1a2e;color:#eee;margin:20px}.card{background:#16213e;border-radius:10px;padding:20px;margin:10px}.badge{padding:5px 10px;border-radius:20px}.success{background:#0f9d58}h1,h2{color:#fff}p{margin:10px 0}</style></head><body>
    <h1>🚂 نظام الانفجارات - Binance الذهبي</h1>
    <div style="display:flex;flex-wrap:wrap">
    <div class="card" style="flex:1"><h2>📊 السوق</h2><p>النظام: {{m.trend}}</p><p>ADX: {{m.adx}} | BTC 1h: {{m.btc_change}}%</p><p>التداول: {{'✅ مسموح' if m.can_trade else '❌ ممنوع'}}</p></div>
    <div class="card" style="flex:1"><h2>💰 الحساب</h2><p>الرصيد: ${{"%.2f"|format(tm.available_capital)}}</p><p>نشطة: {{tm.active_trades|length}}</p><p>اليوم: {{tm.daily_trades}}</p><p>نجاح: {{"%.1f"|format(tm.get_win_rate())}}%</p></div>
    <div class="card" style="flex:1"><h2>🔍 آخر مسح</h2><p>العملات: {{s.scanned}}</p><p>الإشارات: {{s.signals}}</p><p>المدة: {{s.duration}} ث</p></div>
    </div>
    <div class="card"><h2>📁 تحميل</h2><a href="/download/signals">📊 الإشارات</a> | <a href="/download/trades">📈 الصفقات</a></div>
    <p style="text-align:center;opacity:0.7">آخر تحديث: {{now}}</p></body></html>''',
    m=m, s=s, tm=tm, now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/health')
def health(): return jsonify({'status':'healthy'})

@app.route('/download/<ft>')
def download_file(ft):
    files = {'signals':SIGNALS_FILE,'trades':TRADES_FILE}
    if ft in files and os.path.exists(files[ft]): return send_file(files[ft], as_attachment=True)
    return "Not found", 404

def start_flask():
    init_database()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

async def main():
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    engine = ExplosionScannerEngine()
    poller = TelegramPoller(TELEGRAM_TOKEN, engine, engine.notifier)
    asyncio.create_task(poller.start())
    await engine.run()

if __name__ == "__main__":
    asyncio.run(main())
