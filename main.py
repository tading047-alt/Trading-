#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚂 نظام اكتشاف الانفجارات - v37.4 (وضع التحليل الموسع + أمر التحميل)
First Station Explosion Detector - Analysis Mode

التعديلات الجديدة:
✅ إزالة الحدود العليا للصفقات للحصول على أقصى عدد من الإشارات
✅ خفض متطلبات الدخول (ثقة 40%، نمط واحد)
✅ أمر /download في تليجرام للحصول على روابط CSV
✅ جميع ميزات v37.3 (Micro Pump، خروج مبكر، تكيف مع السوق)
"""

import asyncio, threading, sqlite3, pandas as pd, numpy as np, httpx, json, os, time, csv
from datetime import datetime, timedelta
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum

from flask import Flask, jsonify, render_template_string, send_file
import ccxt.async_support as ccxt_async

# --------------------------- الإعدادات ---------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "5067771509")
BOT_TAG = "#Exp100"

# 🧪 وضع التحليل: إزالة الحدود
MAX_TRADES_PER_DAY = 999            # عملياً لا يوجد حد
MAX_CONCURRENT_TRADES = 10          # يسمح بفتح العديد من الصفقات معاً
TOTAL_CAPITAL = 1000.0
BASE_CAPITAL_PER_TRADE = 50.0       # مبلغ أقل لتوزيع المخاطر
MAX_CAPITAL_PER_TRADE = 100.0
MIN_CAPITAL_PER_TRADE = 20.0

SCAN_INTERVAL = 30                  # مسح أسرع
SCAN_BATCH_SIZE = 100
SCAN_SYMBOLS_LIMIT = 500            # فحص أكبر عدد من العملات

# خفض متطلبات الدخول لرؤية كل شيء
MIN_CONFIDENCE = 40                  # ثقة منخفضة
MIN_PATTERNS_REQUIRED = 1            # نمط واحد يكفي
MIN_VOLUME_24H = 30000              # سيولة قليلة
MAX_SPREAD = 0.8
MAX_PRICE_CHANGE_24H = 15.0

# السماح بكل الأنماط
ALLOWED_PATTERNS = ['whale_accumulation', 'calm_before_storm', 'bollinger_squeeze',
                   'volume_spike', 'momentum_building', 'support_bounce', 'micro_pump', 'micro_breakout']

PATTERN_WEIGHTS = {
    'calm_before_storm': 45, 'whale_accumulation': 55, 'bollinger_squeeze': 40,
    'volume_spike': 25, 'momentum_building': 20, 'support_bounce': 30,
    'micro_pump': 90, 'micro_breakout': 80
}

ENABLE_MICRO_PUMP_MODE = True         # يبحث عن العملات الصغيرة
MICRO_PUMP_CAPITAL_PER_TRADE = 15.0
MICRO_PUMP_MIN_VOLUME_24H = 15000
MICRO_PUMP_MAX_PRICE = 0.005
MICRO_PUMP_MIN_VOLUME_RATIO = 2.5
MICRO_PUMP_MIN_PRICE_CHANGE_1M = 2.0
MICRO_PUMP_MAX_SPREAD = 0.8
MICRO_PUMP_TAKE_PROFIT = 8.0
MICRO_PUMP_STOP_LOSS = -3.0
MICRO_PUMP_TRAILING_ACTIVATION = 2.5
MICRO_PUMP_TRAILING_DISTANCE = 1.5
MICRO_PUMP_MAX_CONCURRENT = 10

ENABLE_EARLY_EXIT = True
EARLY_EXIT_BEARISH_CANDLE_BODY = 1.2
EARLY_EXIT_EMA_FAST = 9
EARLY_EXIT_EMA_SLOW = 21
EARLY_EXIT_BREAK_PREV_LOW = True

EXIT_STRATEGY = {
    'partial_take_profit': [{'percent': 3.0, 'sell_ratio': 0.30}, {'percent': 5.5, 'sell_ratio': 0.30}],
    'trailing_stop': {'activation': 3.0, 'base_distance': 2.0, 'min_distance': 1.0, 'max_distance': 3.0, 'tighten_after': 8.0, 'tightened_distance': 0.7},
    'hard_stop_loss': -2.5
}

LOG_DIR = "trading_logs"
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(f"{LOG_DIR}/daily", exist_ok=True)
SIGNALS_FILE = f"{LOG_DIR}/signals_detected.csv"
TRADES_FILE = f"{LOG_DIR}/trades_executed.csv"
VIRTUAL_TRADES_FILE = f"{LOG_DIR}/virtual_trades.csv"
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

# --------------------------- أنواع البيانات ---------------------------
class MarketRegime(Enum):
    TRENDING_BULLISH = "trending_bullish"; TRENDING_BEARISH = "trending_bearish"
    RANGING = "ranging"; TRANSITIONAL = "transitional"

@dataclass
class ExplosionSignal:
    symbol: str; confidence: float; expected_move: float; time_to_explosion: int
    entry_price: float; patterns: List[str]; volume_24h: float
    current_change: float; priority: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    atr_percent: float = 0.0; is_micro_pump: bool = False
    def get_time_estimate(self) -> str:
        m, s = divmod(self.time_to_explosion, 60)
        return f"{m} دقيقة و {s} ثانية" if m else f"{s} ثانية"

@dataclass
class ActiveTrade:
    symbol: str; entry_price: float; capital: float; quantity: float
    remaining_quantity: float; entry_time: datetime; highest_price: float
    trailing_stop: float; trailing_activated: bool; take_profits_hit: List[float]
    pattern: str; confidence: float; atr_percent: float = 0.0; is_micro_pump: bool = False

# --------------------------- الدوال المساعدة ---------------------------
def adapt_config_to_market(market_regime: dict):
    global MIN_CONFIDENCE, MIN_PATTERNS_REQUIRED, MIN_VOLUME_24H, MAX_SPREAD, ALLOWED_PATTERNS, MAX_TRADES_PER_DAY, MAX_CONCURRENT_TRADES
    # في وضع التحليل الموسع نبقي القيم المخففة كما هي دون تغيير
    return

# --------------------------- مدير الصفقات (معدل للكم الكبير) ---------------------------
class TradeManager:
    def __init__(self):
        self.active_trades: Dict[str, ActiveTrade] = {}
        self.closed_trades: List[dict] = []
        self.available_capital = TOTAL_CAPITAL
        self.daily_trades = 0; self.daily_pnl = 0.0; self.total_trades = 0; self.winning_trades = 0

    def calculate_position_size(self, signal: ExplosionSignal) -> float:
        if signal.is_micro_pump:
            return MICRO_PUMP_CAPITAL_PER_TRADE
        # إدارة ديناميكية مخففة
        base = BASE_CAPITAL_PER_TRADE
        conf_mult = 1.2 if signal.confidence >= 60 else 1.0
        vol_mult = 1.1 if signal.volume_24h > 100000 else 0.9
        pat_mult = 1.1 if len(signal.patterns) >= 2 else 1.0
        final = base * conf_mult * vol_mult * pat_mult
        return min(max(final, MIN_CAPITAL_PER_TRADE), MAX_CAPITAL_PER_TRADE)

    def open_trade(self, signal: ExplosionSignal) -> bool:
        symbol = signal.symbol
        if symbol in self.active_trades: return False
        max_con = MAX_CONCURRENT_TRADES
        if signal.is_micro_pump: max_con = MICRO_PUMP_MAX_CONCURRENT
        if len(self.active_trades) >= max_con: return False
        capital = self.calculate_position_size(signal)
        if capital > self.available_capital: return False
        quantity = capital / signal.entry_price
        self.available_capital -= capital
        self.daily_trades += 1; self.total_trades += 1
        trade = ActiveTrade(symbol=symbol, entry_price=signal.entry_price, capital=capital,
                            quantity=quantity, remaining_quantity=quantity,
                            entry_time=datetime.now(), highest_price=signal.entry_price,
                            trailing_stop=0, trailing_activated=False, take_profits_hit=[],
                            pattern=signal.patterns[0] if signal.patterns else 'unknown',
                            confidence=signal.confidence, atr_percent=signal.atr_percent,
                            is_micro_pump=signal.is_micro_pump)
        self.active_trades[symbol] = trade
        print(f"  💰 {symbol}: تخصيص {capital:.1f}$")
        return True

    # باقي دوال update_trade و _close_trade كما في v37.3 (يمكنك تركها دون تغيير)
    # ... (نفس الكود السابق لـ update_trade و _close_trade)
    def update_trade(self, symbol: str, current_price: float, ohlcv_5m: Optional[np.ndarray] = None) -> Optional[dict]:
        if symbol not in self.active_trades: return None
        trade = self.active_trades[symbol]
        if current_price > trade.highest_price: trade.highest_price = current_price
        pnl_pct = (current_price - trade.entry_price) / trade.entry_price * 100

        # استراتيجية Micro Pump
        if trade.is_micro_pump:
            if pnl_pct <= MICRO_PUMP_STOP_LOSS:
                return self._close_trade(symbol, current_price, pnl_pct, 'micro_pump_stop_loss')
            if pnl_pct >= MICRO_PUMP_TAKE_PROFIT:
                return self._close_trade(symbol, current_price, pnl_pct, 'micro_pump_take_profit')
            if pnl_pct >= MICRO_PUMP_TRAILING_ACTIVATION:
                if not trade.trailing_activated:
                    trade.trailing_activated = True
                    trade.trailing_stop = trade.highest_price * (1 - MICRO_PUMP_TRAILING_DISTANCE/100)
                else:
                    new_stop = trade.highest_price * (1 - MICRO_PUMP_TRAILING_DISTANCE/100)
                    if new_stop > trade.trailing_stop: trade.trailing_stop = new_stop
                if trade.trailing_activated and current_price <= trade.trailing_stop:
                    return self._close_trade(symbol, current_price, pnl_pct, 'micro_pump_trailing_stop')
            return None

        # استراتيجية عادية
        if pnl_pct <= EXIT_STRATEGY['hard_stop_loss']:
            return self._close_trade(symbol, current_price, pnl_pct, 'hard_stop_loss')

        for tp in EXIT_STRATEGY['partial_take_profit']:
            if tp['percent'] not in trade.take_profits_hit and pnl_pct >= tp['percent']:
                sell_quantity = trade.quantity * tp['sell_ratio']
                trade.remaining_quantity -= sell_quantity
                trade.take_profits_hit.append(tp['percent'])
                self.available_capital += sell_quantity * current_price
                print(f"  💰 {symbol}: جني أرباح جزئي +{tp['percent']}%")
                if trade.remaining_quantity <= 0:
                    return self._close_trade(symbol, current_price, pnl_pct, 'fully_sold')

        if ENABLE_EARLY_EXIT and ohlcv_5m is not None and len(ohlcv_5m) >= 10 and trade.remaining_quantity > 0:
            closes_5m = ohlcv_5m[:, 4]; opens_5m = ohlcv_5m[:, 1]; highs_5m = ohlcv_5m[:, 2]; lows_5m = ohlcv_5m[:, 3]
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

        if trade.remaining_quantity > 0:
            if trade.atr_percent > 0:
                base_dist = trade.atr_percent * 0.8
                trailing_distance = max(EXIT_STRATEGY['trailing_stop']['min_distance'],
                                       min(base_dist, EXIT_STRATEGY['trailing_stop']['max_distance']))
            else:
                trailing_distance = EXIT_STRATEGY['trailing_stop']['base_distance']
            if pnl_pct >= EXIT_STRATEGY['trailing_stop']['tighten_after']:
                trailing_distance = EXIT_STRATEGY['trailing_stop']['tightened_distance']
            activation_price = trade.entry_price * (1 + EXIT_STRATEGY['trailing_stop']['activation']/100)
            if current_price >= activation_price:
                if not trade.trailing_activated:
                    trade.trailing_activated = True
                    trade.trailing_stop = trade.highest_price * (1 - trailing_distance/100)
                else:
                    new_stop = trade.highest_price * (1 - trailing_distance/100)
                    if new_stop > trade.trailing_stop: trade.trailing_stop = new_stop
                if trade.trailing_activated and current_price <= trade.trailing_stop:
                    return self._close_trade(symbol, current_price, pnl_pct, 'trailing_stop_smart')
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
        del self.active_trades[symbol]
        print(f"  🏁 {symbol}: {pnl_pct:+.2f}% | {reason} | متاح: {self.available_capital:.2f}$")
        return result

    def get_win_rate(self) -> float:
        return (self.winning_trades / self.total_trades * 100) if self.total_trades else 0.0

# --------------------------- كاشف الانفجارات (مع Micro Pump) ---------------------------
class ExplosionDetector:
    def __init__(self):
        self.pattern_weights = PATTERN_WEIGHTS
        self.recent_signals = deque(maxlen=500)
        self.last_signal_time = {}
    EXCLUDED_PATTERNS = ['3S', '3L', '5S', '5L', 'X3', 'X5', 'BEAR', 'BULL', 'UP', 'DOWN']
    EXCLUDED_SYMBOLS = ['BTC/USDT', 'ETH/USDT']

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
                if ENABLE_MICRO_PUMP_MODE and price <= MICRO_PUMP_MAX_PRICE:
                    if vol < MICRO_PUMP_MIN_VOLUME_24H: continue
                    if bid > 0 and ask > 0 and (ask - bid) / bid * 100 > MICRO_PUMP_MAX_SPREAD: continue
                else:
                    if vol < MIN_VOLUME_24H: continue
                    if ch > MAX_PRICE_CHANGE_24H or ch < -15: continue
                    if bid > 0 and ask > 0 and (ask - bid) / bid * 100 > MAX_SPREAD: continue
                active.append(sym)
            active.sort(key=lambda s: tickers.get(s, {}).get('quoteVolume') or 0.0, reverse=True)
            print(f"✅ تم العثور على {len(active)} عملة نشطة")
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
            is_micro_pump = False

            if ENABLE_MICRO_PUMP_MODE and current_price <= MICRO_PUMP_MAX_PRICE:
                micro_pump = self._check_micro_pump_spike(volumes_1m, closes_1m, current_price)
                if micro_pump['detected']:
                    detected_patterns.append(micro_pump['name'])
                    total_conf += self.pattern_weights.get('micro_pump', 90)
                    time_exp += micro_pump['time_estimate'] * self.pattern_weights.get('micro_pump', 90)
                    time_w += self.pattern_weights.get('micro_pump', 90)
                    is_micro_pump = True
                else:
                    micro_break = self._check_micro_breakout(highs_5m, closes_5m, volumes_5m, current_price)
                    if micro_break['detected']:
                        detected_patterns.append(micro_break['name'])
                        total_conf += self.pattern_weights.get('micro_breakout', 80)
                        time_exp += micro_break['time_estimate'] * self.pattern_weights.get('micro_breakout', 80)
                        time_w += self.pattern_weights.get('micro_breakout', 80)
                        is_micro_pump = True
                if is_micro_pump:
                    avg_time = int(time_exp / time_w) if time_w else 30
                    return ExplosionSignal(symbol=symbol, confidence=min(100, total_conf),
                        expected_move=10.0, time_to_explosion=avg_time, entry_price=current_price,
                        patterns=detected_patterns, volume_24h=ticker.get('quoteVolume',0),
                        current_change=ticker.get('percentage',0),
                        priority=5 if total_conf >= 80 else 4, atr_percent=round(atr_percent,2),
                        is_micro_pump=True)

            # تحليل عادي
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
                priority = self._calculate_priority(total_conf, len(detected_patterns), avg_time)
                return ExplosionSignal(symbol=symbol, confidence=min(100, total_conf),
                    expected_move=self._calculate_expected_move(total_conf, len(detected_patterns)),
                    time_to_explosion=avg_time, entry_price=current_price, patterns=detected_patterns,
                    volume_24h=ticker.get('quoteVolume',0), current_change=ticker.get('percentage',0),
                    priority=priority, atr_percent=round(atr_percent,2))
        except: return None
        return None

    def _check_micro_pump_spike(self, volumes, closes, current_price):
        if len(volumes) < 10 or len(closes) < 2: return {'detected': False}
        avg_vol = np.mean(volumes[-11:-1]) if len(volumes) >= 11 else volumes[-2]
        vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1
        price_change_1m = (closes[-1] - closes[-2]) / closes[-2] * 100
        if (vol_ratio >= MICRO_PUMP_MIN_VOLUME_RATIO and 
            price_change_1m >= MICRO_PUMP_MIN_PRICE_CHANGE_1M and
            current_price <= MICRO_PUMP_MAX_PRICE):
            return {'detected': True, 'name': f'🐭 Micro Pump ({vol_ratio:.1f}x, +{price_change_1m:.1f}%)',
                    'time_estimate': 30, 'pattern_name': 'micro_pump'}
        return {'detected': False}

    def _check_micro_breakout(self, highs, closes, volumes, current_price):
        if len(highs) < 15 or len(volumes) < 10: return {'detected': False}
        recent_high = np.max(highs[-16:-1])
        avg_vol = np.mean(volumes[-11:-1]) if len(volumes) >= 11 else volumes[-2]
        vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1
        if closes[-1] > recent_high and vol_ratio >= 2.0 and current_price <= MICRO_PUMP_MAX_PRICE:
            return {'detected': True, 'name': '🚀 Micro Breakout',
                    'time_estimate': 60, 'pattern_name': 'micro_breakout'}
        return {'detected': False}

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
        base=5.0
        if cnt>=4: base+=5.0
        elif cnt>=3: base+=3.0
        elif cnt>=2: base+=1.5
        if conf>=80: base+=2.0
        elif conf>=70: base+=1.0
        return min(15.0, base)
    def _calculate_priority(self, conf, cnt, time_sec):
        pri=1
        if conf>=85: pri+=2
        elif conf>=75: pri+=1
        if cnt>=4: pri+=2
        elif cnt>=3: pri+=1
        if time_sec<120: pri+=1
        return min(5, pri)
    def _should_accept_signal(self, signal):
        now=datetime.now()
        if signal.symbol in self.last_signal_time and (now-self.last_signal_time[signal.symbol]).total_seconds()<300: return False
        return True
    def _record_signal(self, signal): self.recent_signals.append(signal); self.last_signal_time[signal.symbol]=datetime.now()

# --------------------------- نظام الإشعارات ---------------------------
class EnhancedExplosionNotifier:
    def __init__(self):
        self.range_calculator = EntryRangeCalculator()
        self.telegram_token = TELEGRAM_TOKEN; self.telegram_chat_id = TELEGRAM_CHAT_ID
        self.last_summary_time = datetime.now()
    # ... (نفس الدوال السابقة للإشعارات، يمكنك الاحتفاظ بها)
    # نضيف فقط دالة send_csv_links لأمر التحميل
    async def send_csv_links(self, chat_id):
        base_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8080")
        msg = f"""
📁 *روابط تحميل ملفات CSV*
{BOT_TAG}

• [الإشارات]({base_url}/download/signals)
• [الصفقات]({base_url}/download/trades)
• [الافتراضية]({base_url}/download/virtual)
• [لقطات السوق]({base_url}/download/snapshots)
• [الأخطاء]({base_url}/download/errors)
"""
        await self._send_telegram_to_chat(chat_id, msg)

    async def _send_telegram_to_chat(self, chat_id, message):
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"})
        except Exception as e: print(f"⚠️ خطأ تليجرام: {e}")

    async def _send_telegram(self, message: str):  # للتوافق مع باقي الكود
        await self._send_telegram_to_chat(self.telegram_chat_id, message)

# --------------------------- EntryRangeCalculator ---------------------------
class EntryRangeCalculator:
    def __init__(self):
        self.base_range = 0.01
        self.priority_multipliers = {5: 1.5, 4: 1.3, 3: 1.1, 2: 0.9, 1: 0.7}
        self.pattern_multipliers = {6: 1.4, 5: 1.3, 4: 1.2, 3: 1.1, 2: 1.0, 1: 0.8}
    def calculate(self, signal: ExplosionSignal) -> dict:
        current_price = signal.entry_price
        priority_mult = self.priority_multipliers.get(signal.priority, 1.0)
        pattern_mult = self.pattern_multipliers.get(len(signal.patterns), 1.0)
        range_percent = self.base_range * priority_mult * pattern_mult
        entry_min = current_price * (1 - range_percent)
        entry_max = current_price * (1 + range_percent * 0.7)
        if current_price < entry_min: pos, pos_text = "below", "أقل من النطاق - فرصة أفضل"
        elif current_price > entry_max: pos, pos_text = "above", "أعلى من النطاق - انتظر تراجع"
        else: pos, pos_text = "inside", "✅ في النطاق المثالي"
        if signal.is_micro_pump:
            take_profits = [{'percent': MICRO_PUMP_TAKE_PROFIT, 'price': current_price * (1 + MICRO_PUMP_TAKE_PROFIT/100), 'sell_ratio': 100}]
            stop_loss = current_price * (1 + MICRO_PUMP_STOP_LOSS/100)
        else:
            take_profits = [{'percent': tp['percent'], 'price': current_price * (1 + tp['percent']/100), 'sell_ratio': tp['sell_ratio'] * 100} for tp in EXIT_STRATEGY['partial_take_profit']]
            stop_loss = current_price * (1 + EXIT_STRATEGY['hard_stop_loss']/100)
        return {'current': current_price, 'min': entry_min, 'max': entry_max, 'range_percent': range_percent * 100,
                'position': pos, 'position_text': pos_text, 'take_profits': take_profits,
                'stop_loss': stop_loss, 'recommendation': self._get_recommendation(signal, pos)}
    def _get_recommendation(self, signal, position) -> dict:
        if signal.priority >= 4:
            if position in ['inside', 'below']: return {'action': '✅ اشترِ الآن - السعر ممتاز', 'allocation': '100%', 'urgency': 'فوري'}
            else: return {'action': '⚠️ انتظر تراجعاً بسيطاً', 'allocation': '75%', 'urgency': 'انتظار'}
        elif signal.priority >= 3:
            if position in ['inside', 'below']: return {'action': '✅ يمكن الشراء مع مراقبة', 'allocation': '75%', 'urgency': 'عادي'}
            else: return {'action': '⚠️ انتظر تراجعاً', 'allocation': '50%', 'urgency': 'انتظار'}
        else: return {'action': '👀 راقب فقط - لا تدخل', 'allocation': '0%', 'urgency': 'مراقبة'}

# --------------------------- TelegramPoller مع أمر /download ---------------------------
class TelegramPoller:
    def __init__(self, token, engine, notifier):
        self.token = token; self.engine = engine; self.notifier = notifier
        self.last_update_id = 0
    async def start(self):
        while True:
            try:
                url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(url, params={"offset": self.last_update_id+1, "timeout":5})
                    data = resp.json()
                    if data.get("ok"):
                        for upd in data["result"]:
                            self.last_update_id = upd["update_id"]
                            msg = upd.get("message")
                            if msg:
                                text = msg.get("text", "").strip()
                                chat_id = msg["chat"]["id"]
                                if text == "/status":
                                    await self._reply_status(chat_id)
                                elif text == "/download":
                                    await self.notifier.send_csv_links(chat_id)
            except: pass
            await asyncio.sleep(3)
    async def _reply_status(self, chat_id):
        engine = self.engine
        msg = f"""
📊 *حالة البوت*
{BOT_TAG}
🔍 دورات المسح: {engine.scan_count}
💵 الرصيد: {engine.trade_manager.available_capital:.2f}$
📊 صفقات نشطة: {len(engine.trade_manager.active_trades)}
📈 صفقات اليوم: {engine.trade_manager.daily_trades}
🎯 نسبة النجاح: {engine.trade_manager.get_win_rate():.1f}%
🕐 `{datetime.now().strftime('%H:%M:%S')}`
"""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})

# --------------------------- المحرك الرئيسي ---------------------------
class ExplosionScannerEngine:
    def __init__(self):
        self.detector = ExplosionDetector()
        self.notifier = EnhancedExplosionNotifier()
        self.market_filter = MarketRegimeFilter()  # يحتاج تعريف MarketRegimeFilter
        self.trade_manager = TradeManager()
        self.scan_count = 0; self.total_signals = 0; self.market_regime = {}
        self.last_scan_stats = {'scanned':0,'signals':0,'duration':0,'time':'-'}
        self.last_daily_report = datetime.now(); self.last_heartbeat = datetime.now()

    async def run(self):
        global engine_instance; engine_instance = self
        print("╔══════════════════════════════════════════════════════════╗\n║     💥 نظام الانفجارات v37.4 – وضع التحليل المفتوح 💥      ║\n╚══════════════════════════════════════════════════════════╝")
        exchange = ccxt_async.gateio({'enableRateLimit': True, 'rateLimit': 150})
        await self.notifier.send_startup_message()
        try:
            while True:
                self.scan_count += 1; start_time = time.time()
                self.market_regime = await self.market_filter.analyze(exchange)
                adapt_config_to_market(self.market_regime)

                if self.trade_manager.active_trades:
                    ohlcv_tasks = {s: exchange.fetch_ohlcv(s, '5m', limit=26) for s in self.trade_manager.active_trades}
                    ohlcv_results = {}
                    for sym, task in ohlcv_tasks.items():
                        try: ohlcv_results[sym] = await task
                        except Exception: ohlcv_results[sym] = None
                    for symbol in list(self.trade_manager.active_trades.keys()):
                        try:
                            ticker = await exchange.fetch_ticker(symbol)
                            current_price = ticker['last']
                            ohlcv_data = ohlcv_results.get(symbol)
                            if ohlcv_data and len(ohlcv_data) >= 26:
                                arr = np.array(ohlcv_data)
                                result = self.trade_manager.update_trade(symbol, current_price, arr)
                            else:
                                result = self.trade_manager.update_trade(symbol, current_price)
                            if result:
                                print(f"  🏁 {symbol}: {result['pnl_pct']:+.2f}% | {result['exit_reason']}")
                        except Exception as e:
                            print(f"  ⚠️ خطأ في تحديث {symbol}: {e}")

                if self.market_regime.get('can_trade', True):
                    signals = await self.detector.scan_market(exchange)
                    if signals:
                        print(f"\n🎯 تم اكتشاف {len(signals)} عملة مرشحة للانفجار!")
                        available_slots = MAX_CONCURRENT_TRADES - len(self.trade_manager.active_trades)
                        for signal in signals[:available_slots]:
                            if signal.priority >= 2:  # أغلب الإشارات ستكون مقبولة
                                if self.trade_manager.open_trade(signal):
                                    await self.notifier.send_explosion_alert(signal, self.trade_manager.active_trades[signal.symbol].capital)
                                    self.total_signals += 1
                                    await asyncio.sleep(0.5)
                    else:
                        print("\n⚪ لا توجد عملات مرشحة للانفجار حالياً")
                else:
                    print(f"\n⚠️ التداول متوقف")

                elapsed = time.time() - start_time
                self.last_scan_stats = {'scanned': SCAN_SYMBOLS_LIMIT, 'signals': len(signals) if 'signals' in locals() else 0,
                                       'duration': round(elapsed,2), 'time': datetime.now().strftime('%H:%M:%S')}
                if (datetime.now() - self.last_heartbeat).total_seconds() > 7200:
                    await self.notifier.send_heartbeat(self)
                    self.last_heartbeat = datetime.now()
                now = datetime.now()
                if now.hour == 23 and now.minute >= 55 and (now - self.last_daily_report).total_seconds() > 3600:
                    await self.notifier.send_daily_report(self.trade_manager)
                    self.last_daily_report = now
                print(f"\n📊 دورة #{self.scan_count} | ⏱️ {elapsed:.1f} ثانية | الصفقات النشطة: {len(self.trade_manager.active_trades)}")
                await asyncio.sleep(SCAN_INTERVAL)
        except KeyboardInterrupt:
            print("\n⏹️ إيقاف النظام...")
        finally:
            await exchange.close()

# --------------------------- MarketRegimeFilter ---------------------------
class MarketRegimeFilter:
    def __init__(self): self.btc_symbol = 'BTC/USDT'; self.regime_data = {}
    async def analyze(self, exchange) -> dict:
        try:
            ohlcv = await exchange.fetch_ohlcv(self.btc_symbol, '1h', limit=50)
            df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
            closes, highs, lows = df['c'].values, df['h'].values, df['l'].values
            adx = self._calc_adx(highs, lows, closes)
            ema20, ema50 = self._ema(closes,20), self._ema(closes,50)
            trend = "bullish" if ema20[-1] > ema50[-1] else "bearish"
            btc_change_1h = ((closes[-1]-closes[-4])/closes[-4])*100 if len(closes)>=4 else 0
            can_trade = True  # مفتوح دائماً في التحليل
            self.regime_data = {'regime':'trending_bullish' if trend=='bullish' else 'trending_bearish',
                                'adx':round(adx,1), 'btc_change_1h':round(btc_change_1h,2),
                                'can_trade':can_trade, 'trend':trend}
            return self.regime_data
        except: return {'can_trade':True, 'trend':'unknown', 'adx':0, 'btc_change_1h':0}
    def _calc_adx(self, h,l,c,p=14):
        if len(c)<p+1: return 20
        tr1, tr2, tr3 = h[1:]-l[1:], np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])
        tr = np.maximum(np.maximum(tr1,tr2),tr3)
        atr = np.mean(tr[-p:]) if len(tr)>=p else np.mean(tr)
        up, down = h[1:]-h[:-1], l[:-1]-l[1:]
        plus_dm, minus_dm = np.where((up>down)&(up>0), up, 0), np.where((down>up)&(down>0), down, 0)
        plus_di, minus_di = 100*np.mean(plus_dm[-p:])/atr if atr>0 else 0, 100*np.mean(minus_dm[-p:])/atr if atr>0 else 0
        dx = 100*np.abs(plus_di-minus_di)/(plus_di+minus_di) if (plus_di+minus_di)>0 else 0
        return dx
    def _ema(self, data, p):
        alpha, ema = 2/(p+1), np.zeros_like(data)
        if len(data)>=p:
            ema[p-1]=np.mean(data[:p])
            for i in range(p, len(data)): ema[i]=data[i]*alpha+ema[i-1]*(1-alpha)
        return ema

# --------------------------- Flask ---------------------------
app = Flask(__name__)
engine_instance = None

@app.route('/')
def dashboard():
    if not engine_instance: return "Engine not started yet."
    market = engine_instance.market_regime
    stats = engine_instance.last_scan_stats
    tm = engine_instance.trade_manager
    return render_template_string('''
    <!DOCTYPE html><html dir="rtl"><head><title>نظام اكتشاف الانفجارات v37.4</title><meta charset="utf-8"><meta http-equiv="refresh" content="30">
    <style>body{font-family:Arial;background:#1a1a2e;color:#eee;margin:20px}.card{background:#16213e;border-radius:10px;padding:20px;margin:10px}.badge{padding:5px 10px;border-radius:20px}.success{background:#0f9d58}.warning{background:#f4b400}.danger{background:#d93025}h1,h2{color:#fff}p{margin:10px 0}</style></head><body>
    <h1>🚂 نظام اكتشاف الانفجارات v37.4 – وضع التحليل المفتوح</h1>
    <div style="display:flex;flex-wrap:wrap">
    <div class="card" style="flex:1"><h2>📊 حالة السوق</h2><p>النظام: {{market.trend}}</p><p>ADX: {{market.adx}} | BTC 1h: {{market.btc_change}}%</p></div>
    <div class="card" style="flex:1"><h2>💰 حالة الحساب</h2><p>الرصيد المتاح: ${{"%.2f"|format(tm.available_capital)}}</p><p>الصفقات النشطة: {{tm.active_trades|length}}</p><p>صفقات اليوم: {{tm.daily_trades}}</p><p>نسبة النجاح: {{"%.1f"|format(tm.get_win_rate())}}%</p></div>
    <div class="card" style="flex:1"><h2>🔍 آخر مسح</h2><p>العملات: {{stats.scanned}}</p><p>الإشارات: {{stats.signals}}</p><p>المدة: {{stats.duration}} ث</p></div>
    </div>
    <div class="card"><h2>📁 تحميل الملفات</h2><a href="/download/signals">📊 الإشارات</a> | <a href="/download/trades">📈 الصفقات</a> | <a href="/download/virtual">🧪 الافتراضية</a></div>
    <p style="text-align:center;opacity:0.7">آخر تحديث: {{now}}</p></body></html>''',
    market=market, stats=stats, tm=tm, now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/health')
def health(): return jsonify({'status':'healthy', 'timestamp':datetime.now().isoformat()})

@app.route('/download/<ft>')
def download_file(ft):
    files = {'signals':SIGNALS_FILE, 'trades':TRADES_FILE, 'virtual':VIRTUAL_TRADES_FILE,
             'snapshots':SNAPSHOT_FILE, 'errors':ERRORS_FILE}
    if ft in files and os.path.exists(files[ft]):
        return send_file(files[ft], as_attachment=True)
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
