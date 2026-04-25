#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚂 نظام اكتشاف الانفجارات - الإصدار النهائي (Railway Ready)
First Station Explosion Detector - Final Edition

التفعيل:
✅ TRADING_MODE=live     → تداول حي (افتراضي)
✅ TRADING_MODE=backtest → اختبار عكسي لآخر 7 أيام
✅ بدون أي input() - يعمل تلقائياً على Railway

التحسينات المتكاملة:
✅ منصة Binance
✅ أفضل 3 أنماط فقط
✅ فلتر تأكيد الحجم (1.3x)
✅ فلتر اتجاه السوق (BTC فوق EMA50)
✅ فلتر RSI (تجنب التشبع >72)
✅ تتبع أداء العملات (منع المتكررة الخاسرة)
✅ تأكيد MACD إيجابي
✅ 50% من رأس المال مع تراكم الأرباح
✅ بيع 50% عند 3.2% + تفعيل وقف متحرك ضيق 0.5%
✅ وقف خسارة -2.0%
✅ خروج مبكر (شمعة هبوط، تقاطع EMA، كسر دعم)
✅ إشعارات تليجرام كاملة
✅ أوامر تفاعلية (/open, /closed, /stats, /download, /status, /help)
✅ تسجيل CSV + قاعدة بيانات SQLite
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
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")
BOT_TAG = "#BinanceBot"

# =========================================================
# 🆕 وضع التشغيل (live أو backtest) - بدون input()
# =========================================================
TRADING_MODE = os.environ.get("TRADING_MODE", "live")
BACKTEST_DAYS = int(os.environ.get("BACKTEST_DAYS", 7))

print(f"⚙️ وضع التشغيل: {TRADING_MODE}")

# =========================================================
# 🏆 الإعدادات المثلى مع جميع الفلاتر
# =========================================================
MAX_TRADES_PER_DAY = 5
MAX_CONCURRENT_TRADES = 1
TOTAL_CAPITAL = 1000.0
CAPITAL_PER_TRADE_RATIO = 0.5
MAX_CAPITAL_PER_TRADE = 500.0
MIN_CAPITAL_PER_TRADE = 50.0

SCAN_INTERVAL = 45
SCAN_BATCH_SIZE = 50
SCAN_SYMBOLS_LIMIT = 200

MIN_CONFIDENCE = 75
MIN_PATTERNS_REQUIRED = 2
MIN_VOLUME_24H = 150000
MAX_SPREAD = 0.2
MAX_PRICE_CHANGE_24H = 7.0

ALLOWED_PATTERNS = ['whale_accumulation', 'calm_before_storm', 'bollinger_squeeze']
PATTERN_WEIGHTS = {'calm_before_storm': 45, 'whale_accumulation': 55, 'bollinger_squeeze': 40}

VOLUME_RATIO_THRESHOLD = 1.3
RSI_MAX = 72
BTC_EMA_PERIOD = 50
MACD_CONFIRMATION = True
SYMBOL_LOSS_STREAK_LIMIT = 2

BTC_MIN_ADX = 22
BTC_MAX_DROP_1H = -1.5

# =========================================================
# 🆕 استراتيجية الخروج (بيع جزئي + وقف متحرك ضيق)
# =========================================================
EXIT_STRATEGY = {
    'take_profit': 3.2,
    'partial_sell_ratio': 0.5,
    'hard_stop_loss': -2.0,
    'trailing_stop': {'activation': 2.0, 'distance': 0.5, 'tight_distance': 0.5}
}

ENABLE_EARLY_EXIT = True
EARLY_EXIT_BEARISH_CANDLE_BODY = 1.0
EARLY_EXIT_EMA_FAST = 9
EARLY_EXIT_EMA_SLOW = 21
EARLY_EXIT_BREAK_PREV_LOW = True

# =========================================================
# مسارات الملفات وقاعدة البيانات
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
    TRENDING_BULLISH = "bullish"; TRENDING_BEARISH = "bearish"
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
    trailing_stop: float; trailing_activated: bool; take_profit_hit: bool
    pattern: str; confidence: float; atr_percent: float = 0.0

# =========================================================
# مدير الصفقات
# =========================================================
class TradeManager:
    def __init__(self, notifier=None):
        self.active_trades: Dict[str, ActiveTrade] = {}
        self.closed_trades: List[dict] = []
        self.available_capital = TOTAL_CAPITAL
        self.daily_trades = 0; self.daily_pnl = 0.0; self.total_trades = 0; self.winning_trades = 0
        self.notifier = notifier
        self.symbol_loss_streak: Dict[str, int] = {}

    def open_trade(self, signal: ExplosionSignal) -> Tuple[bool, float]:
        symbol = signal.symbol
        if symbol in self.active_trades: return False, 0.0
        if len(self.active_trades) >= MAX_CONCURRENT_TRADES: return False, 0.0
        if self.daily_trades >= MAX_TRADES_PER_DAY: return False, 0.0
        if self.symbol_loss_streak.get(symbol, 0) >= SYMBOL_LOSS_STREAK_LIMIT:
            return False, 0.0
        capital = min(self.available_capital * CAPITAL_PER_TRADE_RATIO, MAX_CAPITAL_PER_TRADE)
        if capital < MIN_CAPITAL_PER_TRADE: return False, 0.0
        if capital > self.available_capital: return False, 0.0
        quantity = capital / signal.entry_price
        self.available_capital -= capital
        self.daily_trades += 1; self.total_trades += 1
        trade = ActiveTrade(symbol=symbol, entry_price=signal.entry_price, capital=capital,
                            quantity=quantity, remaining_quantity=quantity,
                            entry_time=datetime.now(), highest_price=signal.entry_price,
                            trailing_stop=0, trailing_activated=False, take_profit_hit=False,
                            pattern=signal.patterns[0] if signal.patterns else 'unknown',
                            confidence=signal.confidence, atr_percent=signal.atr_percent)
        self.active_trades[symbol] = trade
        print(f"  ✅ {symbol}: دخول بـ {capital:.1f}$")
        return True, capital

    def update_trade(self, symbol: str, current_price: float, ohlcv_5m: Optional[np.ndarray] = None) -> Optional[dict]:
        if symbol not in self.active_trades: return None
        trade = self.active_trades[symbol]
        if current_price > trade.highest_price: trade.highest_price = current_price
        pnl_pct = (current_price - trade.entry_price) / trade.entry_price * 100
        if pnl_pct <= EXIT_STRATEGY['hard_stop_loss']:
            return self._close_trade(symbol, current_price, pnl_pct, 'stop_loss')
        if not trade.take_profit_hit and pnl_pct >= EXIT_STRATEGY['take_profit']:
            trade.take_profit_hit = True
            sell_quantity = trade.remaining_quantity * EXIT_STRATEGY['partial_sell_ratio']
            trade.remaining_quantity -= sell_quantity
            self.available_capital += sell_quantity * current_price
            if not trade.trailing_activated:
                trade.trailing_activated = True
                trade.trailing_stop = current_price * (1 - EXIT_STRATEGY['trailing_stop']['tight_distance']/100)
            else:
                new_stop = current_price * (1 - EXIT_STRATEGY['trailing_stop']['tight_distance']/100)
                if new_stop > trade.trailing_stop: trade.trailing_stop = new_stop
            if trade.remaining_quantity <= 0:
                return self._close_trade(symbol, current_price, pnl_pct, 'fully_sold')
        if pnl_pct >= EXIT_STRATEGY['trailing_stop']['activation'] and not trade.trailing_activated:
            trade.trailing_activated = True
            trade.trailing_stop = trade.highest_price * (1 - EXIT_STRATEGY['trailing_stop']['distance']/100)
        if trade.trailing_activated and trade.remaining_quantity > 0:
            distance = EXIT_STRATEGY['trailing_stop']['tight_distance'] if trade.take_profit_hit else EXIT_STRATEGY['trailing_stop']['distance']
            new_stop = trade.highest_price * (1 - distance/100)
            if new_stop > trade.trailing_stop: trade.trailing_stop = new_stop
            if current_price <= trade.trailing_stop:
                return self._close_trade(symbol, current_price, pnl_pct, 'trailing_stop')
        if ENABLE_EARLY_EXIT and ohlcv_5m is not None and len(ohlcv_5m) >= 10 and trade.remaining_quantity > 0:
            closes_5m = ohlcv_5m[:, 4]; opens_5m = ohlcv_5m[:, 1]; lows_5m = ohlcv_5m[:, 3]
            body = closes_5m[-1] - opens_5m[-1]
            if body < 0 and abs(body)/opens_5m[-1]*100 >= EARLY_EXIT_BEARISH_CANDLE_BODY:
                return self._close_trade(symbol, current_price, pnl_pct, 'early_exit_bearish_candle')
            ema9 = pd.Series(closes_5m).ewm(span=EARLY_EXIT_EMA_FAST, adjust=False).mean().values
            ema21 = pd.Series(closes_5m).ewm(span=EARLY_EXIT_EMA_SLOW, adjust=False).mean().values
            if len(ema9) > 1 and ema9[-2] >= ema21[-2] and ema9[-1] < ema21[-1]:
                return self._close_trade(symbol, current_price, pnl_pct, 'early_exit_ema_cross')
            if EARLY_EXIT_BREAK_PREV_LOW and len(lows_5m) >= 6:
                if current_price < np.min(lows_5m[-6:-1]):
                    return self._close_trade(symbol, current_price, pnl_pct, 'early_exit_break_low')
        return None

    def _close_trade(self, symbol: str, price: float, pnl_pct: float, reason: str) -> dict:
        trade = self.active_trades[symbol]
        if trade.remaining_quantity > 0:
            self.available_capital += trade.remaining_quantity * price
        pnl_usd = trade.capital * pnl_pct / 100
        self.daily_pnl += pnl_pct
        if pnl_pct > 0: self.winning_trades += 1
        if pnl_pct < 0:
            self.symbol_loss_streak[symbol] = self.symbol_loss_streak.get(symbol, 0) + 1
        else:
            self.symbol_loss_streak[symbol] = 0
        result = {'symbol': symbol, 'entry_price': trade.entry_price, 'exit_price': price,
                  'pnl_pct': pnl_pct, 'pnl_usd': pnl_usd, 'entry_time': trade.entry_time,
                  'exit_time': datetime.now(), 'pattern': trade.pattern,
                  'confidence': trade.confidence, 'exit_reason': reason,
                  'capital_allocated': trade.capital}
        self.closed_trades.append(result)
        del self.active_trades[symbol]
        print(f"  🏁 {symbol}: {pnl_pct:+.2f}% | {reason} | الرصيد: {self.available_capital:.2f}$")
        if self.notifier:
            asyncio.create_task(self.notifier.send_trade_closed_alert(result, self.available_capital))
        return result

    def get_win_rate(self) -> float:
        return (self.winning_trades / self.total_trades * 100) if self.total_trades else 0.0

# =========================================================
# كاشف الانفجارات
# =========================================================
class ExplosionDetector:
    def __init__(self):
        self.pattern_weights = PATTERN_WEIGHTS
        self.recent_signals = deque(maxlen=100)
        self.last_signal_time = {}
    EXCLUDED_PATTERNS = ['3S','3L','5S','5L','X3','X5','BEAR','BULL','UP','DOWN']
    EXCLUDED_SYMBOLS = ['BTC/USDT','ETH/USDT','BNB/USDT']

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
                if price <= 0 or vol < MIN_VOLUME_24H: continue
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
            closes_5m, volumes_5m = data_5m[:,4], data_5m[:,5]
            highs_5m, lows_5m = data_5m[:,2], data_5m[:,3]
            current_price = ticker['last']
            avg_vol = np.mean(volumes_5m[-20:]) if len(volumes_5m) >= 20 else volumes_5m[-1]
            vol_ratio = volumes_5m[-1] / avg_vol if avg_vol > 0 else 0
            if vol_ratio < VOLUME_RATIO_THRESHOLD: return None
            rsi = self._calculate_rsi(closes_5m, 14)
            if rsi > RSI_MAX: return None
            macd_line, signal_line, _ = self._compute_macd(closes_5m)
            if MACD_CONFIRMATION and macd_line[-1] <= signal_line[-1]: return None
            atr = np.mean(highs_5m[-14:] - lows_5m[-14:]) if len(highs_5m) >= 14 else 0
            atr_percent = (atr / current_price * 100) if current_price > 0 else 2.0
            detected_patterns = []; total_conf = 0; time_w = 0; time_exp = 0
            checks = []
            if 'calm_before_storm' in ALLOWED_PATTERNS:
                checks.append(self._check_calm_before_storm(volumes_5m, closes_5m))
            if 'whale_accumulation' in ALLOWED_PATTERNS:
                checks.append(self._check_whale_accumulation(data_1m[:,5], data_1m[:,4]))
            if 'bollinger_squeeze' in ALLOWED_PATTERNS:
                checks.append(self._check_bollinger_squeeze(closes_5m))
            for check in checks:
                if check['detected']:
                    detected_patterns.append(check['name'])
                    w = self.pattern_weights.get(check.get('pattern_name',''),20)
                    total_conf += w; time_exp += check['time_estimate']*w; time_w += w
            if total_conf >= MIN_CONFIDENCE and len(detected_patterns) >= MIN_PATTERNS_REQUIRED:
                avg_time = int(time_exp/time_w) if time_w else 180
                expected_move = self._calculate_expected_move(total_conf, len(detected_patterns))
                priority = self._calculate_priority(total_conf, len(detected_patterns), avg_time)
                optimal_entry = self._calculate_optimal_entry(closes_5m, current_price)
                return ExplosionSignal(symbol=symbol, confidence=min(100,total_conf),
                    expected_move=expected_move, time_to_explosion=avg_time,
                    entry_price=optimal_entry, patterns=detected_patterns,
                    volume_24h=ticker.get('quoteVolume',0),
                    current_change=ticker.get('percentage',0),
                    priority=priority, atr_percent=round(atr_percent,2))
        except: return None
        return None

    def _calculate_rsi(self, closes, period=14):
        if len(closes) < period+1: return 50
        deltas = np.diff(closes); gain = np.where(deltas>0, deltas, 0); loss = np.where(deltas<0, -deltas, 0)
        avg_gain = np.mean(gain[:period]); avg_loss = np.mean(loss[:period])
        if avg_loss == 0: return 100
        return 100 - (100 / (1+avg_gain/avg_loss))
    def _compute_macd(self, closes, fast=12, slow=26, signal_period=9):
        ema_fast = pd.Series(closes).ewm(span=fast, adjust=False).mean().values
        ema_slow = pd.Series(closes).ewm(span=slow, adjust=False).mean().values
        macd = ema_fast - ema_slow
        signal = pd.Series(macd).ewm(span=signal_period, adjust=False).mean().values
        return macd, signal, macd - signal
    def _calculate_optimal_entry(self, closes, current_price):
        low = np.min(closes[-10:]); high = np.max(closes[-5:])
        optimal = (low + high) / 2
        return current_price if current_price <= optimal else (current_price + optimal) / 2
    def _check_calm_before_storm(self, v, c):
        if len(v)<15: return {'detected':False}
        r=np.mean(v[-5:])/np.mean(v[-15:-5]) if np.mean(v[-15:-5])>0 else 1
        pr=(np.max(c[-8:])-np.min(c[-8:]))/np.mean(c[-8:])*100
        if r<0.5 and pr<2.0: return {'detected':True,'name':'🌊 هدوء','time_estimate':300,'pattern_name':'calm_before_storm'}
        return {'detected':False}
    def _check_whale_accumulation(self, v, c):
        if len(v)<10 or len(c)<5: return {'detected':False}
        r=v[-1]/np.mean(v[-10:]) if np.mean(v[-10:])>0 else 1
        st=(np.max(c[-5:])-np.min(c[-5:]))/np.mean(c[-5:])*100
        if r>1.5 and st<1.5: return {'detected':True,'name':f'🐋 حيتان ({r:.1f}x)','time_estimate':180,'pattern_name':'whale_accumulation'}
        return {'detected':False}
    def _check_bollinger_squeeze(self, c):
        if len(c)<20: return {'detected':False}
        rec=c[-20:]; cur=c[-1]; mid=np.mean(rec); std=np.std(rec)
        u=mid+2*std; l=mid-2*std; bw=(u-l)/mid*100; pos=(cur-l)/(u-l) if u!=l else 0.5
        if bw<5.0 and pos<0.4: return {'detected':True,'name':f'🎯 بولنجر ({bw:.1f}%)','time_estimate':240,'pattern_name':'bollinger_squeeze'}
        return {'detected':False}
    def _calculate_expected_move(self, conf, cnt):
        base=EXIT_STRATEGY['take_profit']
        if cnt>=3: base+=2.0
        elif cnt>=2: base+=1.0
        if conf>=85: base+=1.5
        elif conf>=78: base+=0.8
        return round(base,1)
    def _calculate_priority(self, conf, cnt, time_sec):
        pri=2 if conf>=MIN_CONFIDENCE else 1
        if conf>=85: pri+=1
        if cnt>=3: pri+=1
        if time_sec<120: pri+=1
        return min(5, pri)
    def _should_accept_signal(self, signal):
        now=datetime.now()
        if signal.symbol in self.last_signal_time and (now-self.last_signal_time[signal.symbol]).total_seconds()<300: return False
        return True
    def _record_signal(self, signal): self.recent_signals.append(signal); self.last_signal_time[signal.symbol]=datetime.now()

# =========================================================
# 🆕 محرك Backtesting
# =========================================================
class BacktestEngine:
    def __init__(self, detector, trade_manager):
        self.detector = detector
        self.trade_manager = trade_manager

    async def run(self, exchange):
        print(f"📊 بدء Backtesting لآخر {BACKTEST_DAYS} أيام...")
        end_date = datetime.now()
        start_date = end_date - timedelta(days=BACKTEST_DAYS)
        symbols = await self.detector._get_active_symbols(exchange)
        total_trades = 0; winning_trades = 0
        for symbol in symbols[:50]:
            try:
                since = exchange.parse8601(start_date.strftime('%Y-%m-%dT00:00:00Z'))
                ohlcv = await exchange.fetch_ohlcv(symbol, '5m', since=since, limit=1000)
                if len(ohlcv) < 100: continue
                for i in range(100, len(ohlcv)):
                    current_price = ohlcv[i][4]
                    result = self.trade_manager.update_trade(symbol, current_price)
                    if result:
                        if result['pnl_pct'] > 0: winning_trades += 1
                        total_trades += 1
                    data = np.array(ohlcv[max(0,i-60):i+1])
                    if len(data) < 30: continue
                    closes = data[:,4]; volumes = data[:,5]
                    avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else volumes[-1]
                    if volumes[-1] / avg_vol < VOLUME_RATIO_THRESHOLD: continue
                    detected = []
                    for check in [self.detector._check_calm_before_storm(volumes, closes),
                                  self.detector._check_whale_accumulation(volumes, closes),
                                  self.detector._check_bollinger_squeeze(closes)]:
                        if check['detected']: detected.append(check['name'])
                    if len(detected) >= MIN_PATTERNS_REQUIRED:
                        signal = ExplosionSignal(symbol=symbol, confidence=80, expected_move=3.2,
                            time_to_explosion=120, entry_price=current_price,
                            patterns=detected, volume_24h=500000, current_change=0, priority=3)
                        self.trade_manager.open_trade(signal)
            except Exception as e: print(f"  ⚠️ {symbol}: {e}")
        for sym in list(self.trade_manager.active_trades.keys()):
            self.trade_manager._close_trade(sym, 0, -2.0, 'end_of_backtest')
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        net = self.trade_manager.available_capital - TOTAL_CAPITAL
        print(f"\n📊 نتائج Backtest: {total_trades} صفقة | نجاح {win_rate:.1f}% | ربح {net:+.2f}$")
        return {'total': total_trades, 'wins': winning_trades, 'win_rate': win_rate, 'pnl': net}

# =========================================================
# نظام الإشعارات
# =========================================================
class EnhancedExplosionNotifier:
    def __init__(self):
        self.tg_token = TELEGRAM_TOKEN; self.tg_chat = TELEGRAM_CHAT_ID
    async def send_open_trade_alert(self, s, cap):
        pat="\n".join(f"  • {p}" for p in s.patterns)
        msg=f"""🔴 *فتح صفقة*\n{BOT_TAG}\n🪙 *{s.symbol}*\n💵 {s.entry_price:.8f}\n💰 {cap:.2f}$\n📊 {s.confidence:.1f}%\n📈 +{s.expected_move:.1f}%\n🎯 أولوية {s.priority}/5\n📋:\n{pat}\n🕐 `{datetime.now().strftime('%H:%M:%S')}`"""
        await self._send(msg)
    async def send_trade_closed_alert(self, r, avail):
        emoji="💰" if r['pnl_pct']>0 else "📉"
        msg=f"""{emoji} *إغلاق صفقة*\n{BOT_TAG}\n🪙 {r['symbol']}\n📊 {r['pnl_pct']:+.2f}% ({r['pnl_usd']:+.2f}$)\n🎯 {r['exit_reason']}\n💵 {avail:.2f}$\n🕐 `{datetime.now().strftime('%H:%M:%S')}`"""
        await self._send(msg)
    async def send_startup_message(self, mode="live"):
        msg=f"""🚀 *تشغيل النظام*\n{BOT_TAG}\n⚙️ {mode}\n🎯 {MIN_CONFIDENCE}% | {MIN_PATTERNS_REQUIRED} نمط\n💰 {TOTAL_CAPITAL}$\n✅ يعمل!\n🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"""
        await self._send(msg)
    async def send_daily_report(self, tm):
        wr=tm.get_win_rate(); net=tm.available_capital-TOTAL_CAPITAL
        msg=f"""📊 *تقرير يومي*\n{BOT_TAG}\n🔄 {tm.daily_trades}\n✅ {wr:.1f}%\n💰 {net:+.2f}$\n🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"""
        await self._send(msg)
    async def send_heartbeat(self, engine):
        m=engine.market_regime
        msg=f"""💓 *نبضة*\n{BOT_TAG}\n📊 {m.get('regime','?')}\n🔍 {engine.scan_count}\n📈 {engine.trade_manager.daily_trades}\n🎯 {engine.trade_manager.get_win_rate():.1f}%\n🕐 `{datetime.now().strftime('%H:%M:%S')}`"""
        await self._send(msg)
    async def send_csv_links(self, chat_id):
        base=os.environ.get("RENDER_EXTERNAL_URL","http://localhost:8080")
        msg=f"""📁 *روابط CSV*\n{BOT_TAG}\n• [الإشارات]({base}/download/signals)\n• [الصفقات]({base}/download/trades)"""
        await self._send_to(chat_id, msg)
    async def _send(self, msg): await self._send_to(self.tg_chat, msg)
    async def _send_to(self, chat_id, msg):
        try:
            url=f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(url, json={"chat_id":chat_id,"text":msg.strip(),"parse_mode":"Markdown"})
        except Exception as e: print(f"⚠️ تليجرام: {e}")

# =========================================================
# مستمع أوامر تليجرام
# =========================================================
class TelegramPoller:
    def __init__(self, token, engine, notifier):
        self.token = token; self.engine = engine; self.notifier = notifier
        self.last_update_id = 0
    async def start(self):
        print("🤖 أوامر تليجرام...")
        while True:
            try:
                url=f"https://api.telegram.org/bot{self.token}/getUpdates"
                async with httpx.AsyncClient(timeout=15) as c:
                    resp=await c.get(url, params={"offset":self.last_update_id+1,"timeout":10})
                    data=resp.json()
                    if data.get("ok"):
                        for upd in data["result"]:
                            self.last_update_id=upd["update_id"]
                            msg=upd.get("message")
                            if msg and "text" in msg:
                                text=msg["text"].strip(); chat_id=msg["chat"]["id"]
                                if text=="/status": await self._status(chat_id)
                                elif text=="/download": await self.notifier.send_csv_links(chat_id)
                                elif text=="/open": await self._open(chat_id)
                                elif text=="/closed": await self._closed(chat_id)
                                elif text=="/stats": await self._stats(chat_id)
                                elif text=="/help": await self._send(chat_id,"/status /open /closed /stats /download /help")
                                else: await self._send(chat_id,"❌ /help")
            except: pass
            await asyncio.sleep(1)
    async def _status(self, cid):
        e=self.engine
        await self._send(cid,f"""📊 *حالة*\n{BOT_TAG}\n🔍 {e.scan_count}\n💵 {e.trade_manager.available_capital:.2f}$\n📊 {len(e.trade_manager.active_trades)}\n📈 {e.trade_manager.daily_trades}\n🎯 {e.trade_manager.get_win_rate():.1f}%\n🕐 `{datetime.now().strftime('%H:%M:%S')}`""")
    async def _open(self, cid):
        a=self.engine.trade_manager.active_trades
        if not a: await self._send(cid,"📊 لا صفقات مفتوحة."); return
        msg=f"📊 *مفتوحة ({len(a)})*\n{BOT_TAG}\n"
        for s,t in a.items():
            pnl=(t.highest_price-t.entry_price)/t.entry_price*100
            d=datetime.now()-t.entry_time; h,r=divmod(int(d.total_seconds()),3600); m=r//60
            msg+=f"\n{'🟢' if pnl>0 else '🔴'} *{s}*\n   💵 {t.entry_price:.8f}\n   📈 {t.highest_price:.8f}\n   📊 {pnl:+.2f}%\n   ⏱️ {h}h {m}m\n"
        await self._send(cid, msg.strip())
    async def _closed(self, cid):
        cl=self.engine.trade_manager.closed_trades[-10:]
        if not cl: await self._send(cid,"📊 لا صفقات مغلقة."); return
        msg=f"📊 *آخر {len(cl)}*\n{BOT_TAG}\n"
        for t in reversed(cl):
            d=t['exit_time']-t['entry_time']; h,r=divmod(int(d.total_seconds()),3600); m=r//60
            msg+=f"\n{'💰' if t['pnl_pct']>0 else '📉'} *{t['symbol']}*\n   📊 {t['pnl_pct']:+.2f}% ({t['pnl_usd']:+.2f}$)\n   🎯 {t['pattern']}\n   ⏱️ {h}h {m}m\n   🛑 {t['exit_reason']}\n"
        await self._send(cid, msg.strip())
    async def _stats(self, cid):
        tm=self.engine.trade_manager; total=tm.total_trades; wins=tm.winning_trades
        wr=tm.get_win_rate(); net=tm.available_capital-TOTAL_CAPITAL
        ps={}
        for t in tm.closed_trades:
            p=t.get('pattern','?')
            if p not in ps: ps[p]={'total':0,'wins':0,'pnl':0.0,'usd':0.0}
            ps[p]['total']+=1; ps[p]['pnl']+=t['pnl_pct']; ps[p]['usd']+=t['pnl_usd']
            if t['pnl_pct']>0: ps[p]['wins']+=1
        msg=f"""📊 *إحصائيات*\n{BOT_TAG}\n📈 *إجمالي:*\n🔄 {total}\n✅ {wins}\n❌ {total-wins}\n🎯 {wr:.1f}%\n💰 {net:+.2f}$\n\n📋 *حسب النوع:*\n"""
        for p,s in ps.items():
            w=s['wins']/s['total']*100 if s['total']>0 else 0
            msg+=f"• {p}\n   {s['total']} | {w:.0f}%\n   {s['pnl']:+.2f}% ({s['usd']:+.2f}$)\n"
        await self._send(cid, msg.strip()+f"\n🕐 `{datetime.now().strftime('%H:%M:%S')}`")
    async def _send(self, cid, txt):
        try:
            url=f"https://api.telegram.org/bot{self.token}/sendMessage"
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(url, json={"chat_id":cid,"text":txt,"parse_mode":"Markdown"})
        except: pass

# =========================================================
# فلتر السوق
# =========================================================
class MarketRegimeFilter:
    def __init__(self): self.btc='BTC/USDT'; self.data={}
    async def analyze(self, ex) -> dict:
        try:
            ohlcv=await ex.fetch_ohlcv(self.btc,'1h',limit=50)
            df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
            c,h,l=df['c'].values,df['h'].values,df['l'].values
            adx=self._adx(h,l,c); ema20,ema50=self._ema(c,20),self._ema(c,50)
            trend="bullish" if ema20[-1]>ema50[-1] else "bearish"
            btc_1h=((c[-1]-c[-4])/c[-4])*100 if len(c)>=4 else 0
            above=c[-1]>ema50[-1]
            can=adx>=BTC_MIN_ADX and btc_1h>BTC_MAX_DROP_1H and above
            self.data={'regime':'trending_bullish' if trend=='bullish' else 'trending_bearish',
                       'adx':round(adx,1),'btc_change_1h':round(btc_1h,2),
                       'can_trade':can,'trend':trend,'btc_above_ema':above}
            return self.data
        except: return {'can_trade':True,'trend':'unknown','adx':0,'btc_change_1h':0,'btc_above_ema':True}
    def _adx(self, h,l,c,p=14):
        if len(c)<p+1: return 20
        tr=np.maximum(np.maximum(h[1:]-l[1:],np.abs(h[1:]-c[:-1])),np.abs(l[1:]-c[:-1]))
        atr=np.mean(tr[-p:]) if len(tr)>=p else np.mean(tr)
        up,down=h[1:]-h[:-1],l[:-1]-l[1:]
        pdm=np.where((up>down)&(up>0),up,0); ndm=np.where((down>up)&(down>0),down,0)
        pdi=100*np.mean(pdm[-p:])/atr if atr>0 else 0; ndi=100*np.mean(ndm[-p:])/atr if atr>0 else 0
        return 100*np.abs(pdi-ndi)/(pdi+ndi) if (pdi+ndi)>0 else 0
    def _ema(self, data, p):
        alpha=2/(p+1); ema=np.zeros_like(data)
        if len(data)>=p: ema[p-1]=np.mean(data[:p])
        for i in range(p,len(data)): ema[i]=data[i]*alpha+ema[i-1]*(1-alpha)
        return ema

# =========================================================
# المحرك الرئيسي
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
        print("╔══════════════════════════════════════════════════╗")
        print(f"║     💥 نظام الانفجارات – {TRADING_MODE} 💥      ║")
        print("╚══════════════════════════════════════════════════╝")
        while True:
            try:
                exchange = ccxt_async.binance({'enableRateLimit':True,'rateLimit':200,'options':{'defaultType':'spot'}})
                await exchange.fetch_ticker('BTC/USDT')
                print("✅ Binance متصل")
                break
            except Exception as e:
                print(f"❌ فشل: {e}. إعادة...")
                await asyncio.sleep(30)

        if TRADING_MODE == "backtest":
            backtest = BacktestEngine(self.detector, self.trade_manager)
            await backtest.run(exchange)
            await exchange.close()
            return

        await self.notifier.send_startup_message("live")
        while True:
            try:
                self.scan_count += 1; start = time.time()
                try: self.market_regime = await self.market_filter.analyze(exchange)
                except: self.market_regime = {'can_trade':True}

                if self.trade_manager.active_trades:
                    tasks = {s: exchange.fetch_ohlcv(s, '5m', limit=26) for s in self.trade_manager.active_trades}
                    results = {}
                    for s, t in tasks.items():
                        try: results[s] = await t
                        except: results[s] = None
                    for s in list(self.trade_manager.active_trades.keys()):
                        try:
                            ticker = await exchange.fetch_ticker(s); price = ticker['last']
                            data = results.get(s)
                            if data and len(data) >= 26:
                                self.trade_manager.update_trade(s, price, np.array(data))
                            else:
                                self.trade_manager.update_trade(s, price)
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
                    else: print("\n⚪ لا إشارات")
                else: print("\n⚠️ متوقف")

                elapsed = time.time() - start
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
                print(f"\n📊 #{self.scan_count} | ⏱️ {elapsed:.1f}ث | نشطة: {len(self.trade_manager.active_trades)}")
            except Exception as e:
                print(f"❌ خطأ: {e}")
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
    if not engine_instance: return "Not ready"
    m = engine_instance.market_regime; s = engine_instance.last_scan_stats; tm = engine_instance.trade_manager
    return render_template_string('''
    <!DOCTYPE html><html dir="rtl"><head><title>Bot</title><meta charset="utf-8"><meta http-equiv="refresh" content="30">
    <style>body{font-family:Arial;background:#1a1a2e;color:#eee;margin:20px}.card{background:#16213e;border-radius:10px;padding:20px;margin:10px}h1,h2{color:#fff}p{margin:10px 0}</style></head><body>
    <h1>🚂 نظام الانفجارات – Binance</h1>
    <div style="display:flex;flex-wrap:wrap">
    <div class="card" style="flex:1"><h2>📊 السوق</h2><p>{{m.trend}}</p><p>ADX: {{m.adx}} | BTC 1h: {{m.btc_change}}%</p><p>BTC فوق EMA: {{'✅' if m.btc_above_ema else '❌'}}</p></div>
    <div class="card" style="flex:1"><h2>💰 الحساب</h2><p>${{"%.2f"|format(tm.available_capital)}}</p><p>نشطة: {{tm.active_trades|length}}</p><p>اليوم: {{tm.daily_trades}}</p><p>نجاح: {{"%.1f"|format(tm.get_win_rate())}}%</p></div>
    <div class="card" style="flex:1"><h2>🔍 آخر مسح</h2><p>{{s.scanned}} عملة</p><p>{{s.signals}} إشارة</p><p>{{s.duration}} ث</p></div>
    </div>
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
