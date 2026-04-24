#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚂 نظام اكتشاف الانفجارات - الإصدار v37.3 (صائد الـ Micro Pump)
First Station Explosion Detector - Micro Pump Hunter Edition

التحسينات الجديدة:
✅ وضع صائد العملات الصغيرة (Micro Pump) برأس مال صغير
✅ كشف انفجارات الحجم والزخم في العملات الرخيصة
✅ كشف اختراقات القمم بحجم كبير
✅ خروج مبكر عند شمعة هبوط / تقاطع EMA / كسر دعم
✅ إعدادات تتكيف مع حالة السوق
✅ إدارة مخاطر ديناميكية + وقف متحرك ذكي
✅ استبعاد العملات الكبيرة والرافعة
✅ نبض قلب يظهر حالة السوق الحالية
"""

import asyncio
import threading
from flask import Flask, jsonify, render_template_string, send_file
import sqlite3
import ccxt.async_support as ccxt_async
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
import httpx
import json
import os
import time
import csv
from collections import deque
from enum import Enum

# =========================================================
# إعدادات تليجرام
# =========================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "5067771509")
BOT_TAG = "#Exp100"

# =========================================================
# 🐭 إعدادات وضع Micro Pump
# =========================================================
ENABLE_MICRO_PUMP_MODE = True                # تفعيل وضع صائد العملات الصغيرة
MICRO_PUMP_CAPITAL_PER_TRADE = 15.0          # مبلغ صغير جداً (10$-20$)
MICRO_PUMP_MIN_VOLUME_24H = 15000            # سيولة منخفضة (عملات صغيرة)
MICRO_PUMP_MAX_PRICE = 0.005                 # السعر أقل من نصف سنت (عملات رخيصة)
MICRO_PUMP_MIN_VOLUME_RATIO = 3.0            # حجم تداول 3x المتوسط
MICRO_PUMP_MIN_PRICE_CHANGE_1M = 2.5         # ارتفاع 2.5% في دقيقة واحدة
MICRO_PUMP_MAX_SPREAD = 0.8                  # تقبل سبريد أعلى قليلاً
MICRO_PUMP_TAKE_PROFIT = 8.0                 # هدف ربح سريع 8%
MICRO_PUMP_STOP_LOSS = -3.0                 # وقف خسارة أضيق قليلاً
MICRO_PUMP_TRAILING_ACTIVATION = 2.5         # تفعيل وقف متحرك مبكراً
MICRO_PUMP_TRAILING_DISTANCE = 1.5           # مسافة وقف متحرك ضيقة
MICRO_PUMP_MAX_CONCURRENT = 5                # السماح بصفقات أكثر
MICRO_PUMP_PRIORITY_MIN = 4                  # يتطلب أولوية عالية (إشارة قوية جداً)

# =========================================================
# الإعدادات الأساسية (سيتم تعديلها تلقائياً حسب السوق)
# =========================================================
TOTAL_CAPITAL = 1000.0
MAX_TRADES_PER_DAY = 6
BASE_CAPITAL_PER_TRADE = 80.0
MAX_CAPITAL_PER_TRADE = 200.0
MIN_CAPITAL_PER_TRADE = 50.0
MAX_CONCURRENT_TRADES = 3

SCAN_INTERVAL = 45
SCAN_BATCH_SIZE = 50
SCAN_SYMBOLS_LIMIT = 350

MIN_CONFIDENCE = 72
MIN_PATTERNS_REQUIRED = 2
MIN_VOLUME_24H = 130000
MAX_SPREAD = 0.22
MAX_PRICE_CHANGE_24H = 7.5

PATTERN_WEIGHTS = {
    'calm_before_storm': 45,
    'whale_accumulation': 55,
    'bollinger_squeeze': 40,
    'volume_spike': 25,
    'momentum_building': 20,
    'support_bounce': 30,
    'micro_pump': 90,          # وزن عالي لصيد الـ pump
    'micro_breakout': 80
}

ALLOWED_PATTERNS = ['whale_accumulation', 'calm_before_storm', 'bollinger_squeeze']
BTC_MIN_ADX = 22
BTC_MAX_DROP_1H = -1.5

# =========================================================
# 🆕 إعدادات الخروج المبكر
# =========================================================
ENABLE_EARLY_EXIT = True
EARLY_EXIT_BEARISH_CANDLE_BODY = 1.2
EARLY_EXIT_EMA_FAST = 9
EARLY_EXIT_EMA_SLOW = 21
EARLY_EXIT_BREAK_PREV_LOW = True

# =========================================================
# 🎯 استراتيجية الخروج المتكاملة (تُعدل عند Micro Pump)
# =========================================================
EXIT_STRATEGY = {
    'partial_take_profit': [
        {'percent': 3.0, 'sell_ratio': 0.30},
        {'percent': 5.5, 'sell_ratio': 0.30},
    ],
    'trailing_stop': {
        'activation': 3.0,
        'base_distance': 2.0,
        'min_distance': 1.0,
        'max_distance': 3.0,
        'tighten_after': 8.0,
        'tightened_distance': 0.7
    },
    'hard_stop_loss': -2.5
}

# =========================================================
# إعدادات الملفات وقاعدة البيانات
# =========================================================
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
                  daily_trades INTEGER, win_rate REAL, market_regime TEXT,
                  btc_change REAL, last_update TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS trades_archive
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  symbol TEXT, entry_price REAL, exit_price REAL,
                  pnl_pct REAL, pnl_usd REAL, entry_time TEXT,
                  exit_time TEXT, pattern TEXT, status TEXT)''')
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

# =========================================================
# أنواع البيانات
# =========================================================
class MarketRegime(Enum):
    TRENDING_BULLISH = "trending_bullish"
    TRENDING_BEARISH = "trending_bearish"
    RANGING = "ranging"
    TRANSITIONAL = "transitional"

@dataclass
class ExplosionSignal:
    symbol: str; confidence: float; expected_move: float; time_to_explosion: int
    entry_price: float; patterns: List[str]; volume_24h: float
    current_change: float; priority: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    atr_percent: float = 0.0
    is_micro_pump: bool = False  # 🆕 لتمييز صفقات الـ pump
    def get_time_estimate(self) -> str:
        m, s = divmod(self.time_to_explosion, 60)
        return f"{m} دقيقة و {s} ثانية" if m else f"{s} ثانية"

@dataclass
class ActiveTrade:
    symbol: str; entry_price: float; capital: float; quantity: float
    remaining_quantity: float; entry_time: datetime; highest_price: float
    trailing_stop: float; trailing_activated: bool; take_profits_hit: List[float]
    pattern: str; confidence: float; atr_percent: float = 0.0
    is_micro_pump: bool = False

# =========================================================
# دالة التكيف مع السوق (معدلة لدعم Micro Pump)
# =========================================================
def adapt_config_to_market(market_regime: dict):
    global MIN_CONFIDENCE, MIN_PATTERNS_REQUIRED, MIN_VOLUME_24H, MAX_SPREAD, ALLOWED_PATTERNS, MAX_TRADES_PER_DAY, MAX_CONCURRENT_TRADES

    if ENABLE_MICRO_PUMP_MODE:
        # في وضع Micro Pump، نسمح بإشارات الـ pump فقط
        ALLOWED_PATTERNS = ['micro_pump', 'micro_breakout', 'whale_accumulation']
        # نترك باقي الإعدادات واسعة نسبياً
        MIN_CONFIDENCE = 50
        MIN_PATTERNS_REQUIRED = 1
        MIN_VOLUME_24H = 5000
        MAX_SPREAD = 1.0
        MAX_CONCURRENT_TRADES = MICRO_PUMP_MAX_CONCURRENT
        print("🐭 وضع Micro Pump نشط: البحث عن عملات صغيرة تنفجر")
        return

    adx = market_regime.get('adx', 20); trend = market_regime.get('trend', 'unknown'); btc_change = market_regime.get('btc_change_1h', 0)
    if trend == 'bullish' and adx > 25 and btc_change > 0:
        MIN_CONFIDENCE=70; MIN_PATTERNS_REQUIRED=2; MIN_VOLUME_24H=100000; MAX_SPREAD=0.3
        ALLOWED_PATTERNS=['whale_accumulation','calm_before_storm','bollinger_squeeze','support_bounce']
        MAX_TRADES_PER_DAY=6; MAX_CONCURRENT_TRADES=3
    elif adx < 22:
        MIN_CONFIDENCE=80; MIN_PATTERNS_REQUIRED=3; MIN_VOLUME_24H=200000; MAX_SPREAD=0.2
        ALLOWED_PATTERNS=['whale_accumulation','bollinger_squeeze']
        MAX_TRADES_PER_DAY=3; MAX_CONCURRENT_TRADES=2
    elif trend == 'bearish' or btc_change < -1.0:
        MIN_CONFIDENCE=85; MIN_PATTERNS_REQUIRED=3; MIN_VOLUME_24H=300000; MAX_SPREAD=0.15
        ALLOWED_PATTERNS=['whale_accumulation']; MAX_TRADES_PER_DAY=2; MAX_CONCURRENT_TRADES=1
    else:
        MIN_CONFIDENCE=75; MIN_PATTERNS_REQUIRED=2; MIN_VOLUME_24H=150000; MAX_SPREAD=0.25
        ALLOWED_PATTERNS=['whale_accumulation','calm_before_storm']
        MAX_TRADES_PER_DAY=4; MAX_CONCURRENT_TRADES=2

# =========================================================
# حاسبة نطاق الدخول (كما هي)
# =========================================================
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
        # بالنسبة لـ micro pump، نعرض أهداف خاصة
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

# =========================================================
# مدير الصفقات (يدعم Micro Pump)
# =========================================================
class TradeManager:
    def __init__(self):
        self.active_trades: Dict[str, ActiveTrade] = {}
        self.closed_trades: List[dict] = []
        self.available_capital = TOTAL_CAPITAL
        self.daily_trades = 0; self.daily_pnl = 0.0; self.total_trades = 0; self.winning_trades = 0

    def calculate_position_size(self, signal: ExplosionSignal) -> float:
        if signal.is_micro_pump:
            return MICRO_PUMP_CAPITAL_PER_TRADE
        base = BASE_CAPITAL_PER_TRADE
        if signal.confidence >= 85: conf_mult = 1.5
        elif signal.confidence >= 78: conf_mult = 1.3
        elif signal.confidence >= 72: conf_mult = 1.0
        else: conf_mult = 0.7
        if signal.volume_24h > 500000: vol_mult = 1.2
        elif signal.volume_24h > 200000: vol_mult = 1.0
        else: vol_mult = 0.8
        pat_mult = 1.2 if len(signal.patterns) >= 3 else 1.0 if len(signal.patterns) >= 2 else 0.8
        pri_mult = 0.8 + (signal.priority - 1) * 0.15
        final = base * conf_mult * vol_mult * pat_mult * pri_mult
        return min(max(final, MIN_CAPITAL_PER_TRADE), MAX_CAPITAL_PER_TRADE)

    def open_trade(self, signal: ExplosionSignal) -> bool:
        symbol = signal.symbol
        if symbol in self.active_trades:
            return False
        max_con = MAX_CONCURRENT_TRADES
        max_daily = MAX_TRADES_PER_DAY
        if signal.is_micro_pump:
            max_con = MICRO_PUMP_MAX_CONCURRENT
        if len(self.active_trades) >= max_con or self.daily_trades >= max_daily:
            return False
        capital = self.calculate_position_size(signal)
        if capital > self.available_capital:
            return False
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
        print(f"  💰 {symbol}: تخصيص {capital:.1f}$ {'(Micro Pump)' if signal.is_micro_pump else ''}")
        return True

    def update_trade(self, symbol: str, current_price: float, ohlcv_5m: Optional[np.ndarray] = None) -> Optional[dict]:
        if symbol not in self.active_trades: return None
        trade = self.active_trades[symbol]
        if current_price > trade.highest_price: trade.highest_price = current_price
        pnl_pct = (current_price - trade.entry_price) / trade.entry_price * 100

        # استراتيجية خروج مختلفة لصفقات Micro Pump
        if trade.is_micro_pump:
            if pnl_pct <= MICRO_PUMP_STOP_LOSS:
                return self._close_trade(symbol, current_price, pnl_pct, 'micro_pump_stop_loss')
            if pnl_pct >= MICRO_PUMP_TAKE_PROFIT:
                return self._close_trade(symbol, current_price, pnl_pct, 'micro_pump_take_profit')
            # وقف متحرك بمسافة ضيقة
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

        # فيما يلي الاستراتيجية العادية
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

# =========================================================
# كاشف الانفجارات (مع ميزة Micro Pump)
# =========================================================
class ExplosionDetector:
    def __init__(self):
        self.pattern_weights = PATTERN_WEIGHTS
        self.recent_signals = deque(maxlen=100)
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
            await asyncio.sleep(0.3)
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
                # فلترة Micro Pump
                if ENABLE_MICRO_PUMP_MODE:
                    if price > MICRO_PUMP_MAX_PRICE or price <= 0: continue
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
                    micro_break = self._check_micro_breakout(highs_5m, closes_5m, volumes_5m, current_price, ticker)
                    if micro_break['detected']:
                        detected_patterns.append(micro_break['name'])
                        total_conf += self.pattern_weights.get('micro_breakout', 80)
                        time_exp += micro_break['time_estimate'] * self.pattern_weights.get('micro_breakout', 80)
                        time_w += self.pattern_weights.get('micro_breakout', 80)
                        is_micro_pump = True
                # إذا لم نجد Micro Pump، نسمح بتحليل الأنماط العادية (خاصة الحيتان)
                if not is_micro_pump:
                    # يمكن أيضاً إضافة الأنماط العادية للعملات الصغيرة
                    pass
                else:
                    # تخطي الأنماط الأخرى إذا وجدنا pump
                    if total_conf >= MIN_CONFIDENCE:
                        avg_time = int(time_exp / time_w) if time_w else 30
                        return ExplosionSignal(symbol=symbol, confidence=min(100, total_conf),
                            expected_move=10.0, time_to_explosion=avg_time, entry_price=current_price,
                            patterns=detected_patterns, volume_24h=ticker.get('quoteVolume',0),
                            current_change=ticker.get('percentage',0),
                            priority=5 if total_conf >= 80 else 4, atr_percent=round(atr_percent,2),
                            is_micro_pump=True)

            # إذا لم نكن في وضع Micro Pump أو لم تتحقق شروطه، تابع التحليل العادي
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
                return ExplosionSignal(symbol=symbol, confidence=min(100, total_conf),
                    expected_move=self._calculate_expected_move(total_conf, len(detected_patterns)),
                    time_to_explosion=avg_time, entry_price=current_price, patterns=detected_patterns,
                    volume_24h=ticker.get('quoteVolume',0), current_change=ticker.get('percentage',0),
                    priority=self._calculate_priority(total_conf, len(detected_patterns), avg_time),
                    atr_percent=round(atr_percent,2))
        except: return None
        return None

    # 🆕 دوال كشف Micro Pump
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

    def _check_micro_breakout(self, highs, closes, volumes, current_price, ticker):
        if len(highs) < 15 or len(volumes) < 10: return {'detected': False}
        recent_high = np.max(highs[-16:-1])
        avg_vol = np.mean(volumes[-11:-1]) if len(volumes) >= 11 else volumes[-2]
        vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1
        if closes[-1] > recent_high and vol_ratio >= 2.0 and current_price <= MICRO_PUMP_MAX_PRICE:
            return {'detected': True, 'name': '🚀 Micro Breakout', 
                    'time_estimate': 60, 'pattern_name': 'micro_breakout'}
        return {'detected': False}

    # الدوال القديمة (مختصرة)
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

# =========================================================
# نظام الإشعارات (كما هو)
# =========================================================
class EnhancedExplosionNotifier:
    def __init__(self):
        self.range_calculator = EntryRangeCalculator()
        self.telegram_token = TELEGRAM_TOKEN; self.telegram_chat_id = TELEGRAM_CHAT_ID
        self.last_summary_time = datetime.now()

    async def send_explosion_alert(self, signal: ExplosionSignal, capital_allocated: float = 0):
        range_info = self.range_calculator.calculate(signal)
        prio_emoji = "🔴🔴🔴" if signal.priority>=5 else "🔴🔴" if signal.priority>=4 else "🔴" if signal.priority>=3 else "🟡"
        patterns_msg = "\n".join(f"  • {p}" for p in signal.patterns)
        cap_msg = f"\n💰 رأس المال المخصص: {capital_allocated:.1f}$" if capital_allocated>0 else ""
        msg = f"""
{prio_emoji} *{'🐭 Micro Pump' if signal.is_micro_pump else 'انفجار قادم'} - أولوية {signal.priority}/5*
{BOT_TAG}

🪙 *{signal.symbol}*
💰 السعر الحالي: {signal.entry_price:.8f}
📊 الثقة: {signal.confidence:.1f}%
📈 الصعود المتوقع: +{signal.expected_move:.1f}%
⏱️ الوقت المتوقع: {signal.get_time_estimate()}
📊 تقلب ATR: {signal.atr_percent:.1f}%
{cap_msg}
📋 *الأنماط المكتشفة:*
{patterns_msg}
{self._format_entry_range_message(signal, range_info)}
📊 حجم 24h: ${signal.volume_24h:,.0f}
📈 التغير الحالي: {signal.current_change:+.2f}%

🕐 `{datetime.now().strftime('%H:%M:%S')}`
"""
        await self._send_telegram(msg)

    def _format_entry_range_message(self, signal, range_info):
        rec = range_info['recommendation']
        targets_msg = "".join(f"   🎯 هدف {i}: +{tp['percent']}% ({tp['price']:.8f}) - بيع {tp['sell_ratio']:.0f}%\n" for i,tp in enumerate(range_info['take_profits'],1))
        return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 *نطاق الدخول المثالي*

📊 *النطاق الآمن:*
   • الحد الأدنى: {range_info['min']:.8f} (-{range_info['range_percent']:.1f}%)
   • الحد الأقصى: {range_info['max']:.8f} (+{range_info['range_percent']*0.7:.1f}%)
   • السعر الحالي: {range_info['current']:.8f} {range_info['position_text']}

💡 *توصية الدخول:*
   {rec['action']}
   💰 حجم الصفقة: {rec['allocation']}

📈 *استراتيجية الخروج:*
{targets_msg}
   🔄 وقف متحرك ذكي: تفعيل +{EXIT_STRATEGY['trailing_stop']['activation']}% | مسافة ديناميكية
   🛑 وقف خسارة: {EXIT_STRATEGY['hard_stop_loss']}% ({range_info['stop_loss']:.8f})

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

    async def send_startup_message(self):
        mode = "🐭 Micro Pump Hunter" if ENABLE_MICRO_PUMP_MODE else "العادي"
        msg = f"""
🚀 *تم تشغيل نظام الانفجارات التكيفي*
{BOT_TAG}

🔍 مسح {SCAN_SYMBOLS_LIMIT} عملة | {SCAN_INTERVAL} ثانية
🎯 الوضع: {mode}
💰 رأس المال: {TOTAL_CAPITAL}$ ({MAX_TRADES_PER_DAY} صفقة يومياً)
🛡️ خروج مبكر: {'مفعل' if ENABLE_EARLY_EXIT else 'معطل'}
✅ *النظام يعمل بنجاح!*
🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
"""
        await self._send_telegram(msg)

    async def send_daily_report(self, trade_manager: TradeManager):
        win_rate = trade_manager.get_win_rate()
        net_pnl = trade_manager.available_capital - TOTAL_CAPITAL
        net_pnl_pct = (net_pnl / TOTAL_CAPITAL) * 100
        msg = f"""
📊 *التقرير اليومي*
{BOT_TAG}
📅 *{datetime.now().strftime('%Y-%m-%d')}*
📈 *إحصائيات اليوم:*
🔄 إجمالي الصفقات: {trade_manager.daily_trades}
✅ الصفقات الرابحة: {trade_manager.winning_trades}
❌ الصفقات الخاسرة: {trade_manager.daily_trades - trade_manager.winning_trades}
🎯 نسبة النجاح: {win_rate:.1f}%
💰 صافي الربح: {net_pnl:+.2f}$ ({net_pnl_pct:+.2f}%)
💵 الرصيد الحالي: {trade_manager.available_capital:.2f}$
🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
"""
        await self._send_telegram(msg)

    async def send_heartbeat(self, engine):
        market = engine.market_regime
        msg = f"""
💓 *نبضة قلب - النظام يعمل*
{BOT_TAG}
📊 *حالة السوق:* {market.get('regime','غير معروف').replace('trending_bullish','🟢 صاعد').replace('trending_bearish','🔴 هابط').replace('ranging','🟡 جانبي')}
📈 ADX: {market.get('adx',0)} | BTC 1h: {market.get('btc_change_1h',0):+.2f}%
🔍 دورات المسح: {engine.scan_count}
📊 الصفقات النشطة: {len(engine.trade_manager.active_trades)}
💵 الرصيد المتاح: {engine.trade_manager.available_capital:.2f}$
📈 صفقات اليوم: {engine.trade_manager.daily_trades}
🎯 الإعدادات الحالية: ثقة ≥ {MIN_CONFIDENCE}% | أنماط ≥ {MIN_PATTERNS_REQUIRED}
🕐 `{datetime.now().strftime('%H:%M:%S')}`
"""
        await self._send_telegram(msg)

    async def _send_telegram(self, message: str):
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json={"chat_id": self.telegram_chat_id, "text": message.strip(), "parse_mode": "Markdown"})
        except Exception as e: print(f"⚠️ خطأ تليجرام: {e}")

# =========================================================
# فلتر السوق (معدل لـ Micro Pump)
# =========================================================
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
            # في وضع Micro Pump، نتجاهل تقييد السوق
            if ENABLE_MICRO_PUMP_MODE:
                can_trade = True
            else:
                can_trade = adx >= BTC_MIN_ADX and btc_change_1h > BTC_MAX_DROP_1H
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

# =========================================================
# Flask + المحرك الرئيسي (مع دعم Micro Pump)
# =========================================================
app = Flask(__name__)
engine_instance = None

@app.route('/')
def dashboard():
    if not engine_instance: return "Engine not started yet."
    market = engine_instance.market_regime
    stats = engine_instance.last_scan_stats
    tm = engine_instance.trade_manager
    return render_template_string('''
    <!DOCTYPE html><html dir="rtl"><head><title>نظام اكتشاف الانفجارات v37.3</title><meta charset="utf-8"><meta http-equiv="refresh" content="30">
    <style>body{font-family:Arial;background:#1a1a2e;color:#eee;margin:20px}.card{background:#16213e;border-radius:10px;padding:20px;margin:10px}.badge{padding:5px 10px;border-radius:20px}.success{background:#0f9d58}.warning{background:#f4b400}.danger{background:#d93025}h1,h2{color:#fff}p{margin:10px 0}.strategy-box{background:#0f3460;border-radius:8px;padding:15px;margin:10px 0}</style></head><body>
    <h1>🚂 نظام اكتشاف الانفجارات v37.3 – Micro Pump Hunter</h1>
    <div style="display:flex;flex-wrap:wrap">
    <div class="card" style="flex:1"><h2>📊 حالة السوق</h2><p>النظام: <span class="badge {{'success' if market.trend=='bullish' else 'danger'}}">{{market.trend}}</span></p><p>ADX: {{market.adx}}</p><p>BTC 1h: {{market.btc_change}}%</p><p>التداول: {{'✅ مسموح' if market.can_trade else '❌ ممنوع'}}</p></div>
    <div class="card" style="flex:1"><h2>💰 حالة الحساب</h2><p>الرصيد المتاح: ${{"%.2f"|format(tm.available_capital)}}</p><p>الصفقات النشطة: {{tm.active_trades|length}}</p><p>صفقات اليوم: {{tm.daily_trades}}/{{max_daily}}</p><p>نسبة النجاح: {{"%.1f"|format(tm.get_win_rate())}}%</p></div>
    <div class="card" style="flex:1"><h2>🔍 آخر مسح</h2><p>العملات: {{stats.scanned}}</p><p>الإشارات: {{stats.signals}}</p><p>المدة: {{stats.duration}} ثانية</p><p>الوقت: {{stats.time}}</p></div>
    </div>
    <div class="card"><h2>⚙️ استراتيجية الخروج النشطة</h2><div class="strategy-box"><p>🐭 <strong>Micro Pump:</strong> تفعيل</p><p>🎯 <strong>هدف ربح:</strong> {MICRO_PUMP_TAKE_PROFIT}% | 🛑 <strong>وقف خسارة:</strong> {MICRO_PUMP_STOP_LOSS}%</p><p>🔄 <strong>وقف متحرك:</strong> تفعيل عند {MICRO_PUMP_TRAILING_ACTIVATION}% | مسافة {MICRO_PUMP_TRAILING_DISTANCE}%</p></div></div>
    <p style="text-align:center;opacity:0.7">آخر تحديث: {{now}}</p></body></html>''',
    market=market, stats=stats, tm=tm, max_daily=MAX_TRADES_PER_DAY, now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/health')
def health(): return jsonify({'status':'healthy', 'timestamp':datetime.now().isoformat()})

class TelegramPoller:
    def __init__(self, token, engine): self.token=token; self.engine=engine; self.last_update_id=0
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
                            if msg and msg.get("text","").strip()=="/status":
                                await self._reply_status(msg["chat"]["id"])
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

class ExplosionScannerEngine:
    def __init__(self):
        self.detector = ExplosionDetector()
        self.notifier = EnhancedExplosionNotifier()
        self.market_filter = MarketRegimeFilter()
        self.trade_manager = TradeManager()
        self.scan_count = 0; self.total_signals = 0; self.market_regime = {}
        self.last_scan_stats = {'scanned':0,'signals':0,'duration':0,'time':'-'}
        self.last_daily_report = datetime.now(); self.last_heartbeat = datetime.now()

    async def run(self):
        global engine_instance; engine_instance = self
        print("╔══════════════════════════════════════════════════════════╗\n║     💥 نظام الانفجارات v37.3 – Micro Pump Hunter 💥      ║\n╚══════════════════════════════════════════════════════════╝")
        exchange = ccxt_async.gateio({'enableRateLimit': True, 'rateLimit': 150})
        await self.notifier.send_startup_message()
        try:
            while True:
                self.scan_count += 1; start_time = time.time()
                self.market_regime = await self.market_filter.analyze(exchange)
                adapt_config_to_market(self.market_regime)

                # تحديث الصفقات النشطة مع جلب بيانات OHLCV لدعم الخروج المبكر
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
                        if ENABLE_MICRO_PUMP_MODE:
                            available_slots = MICRO_PUMP_MAX_CONCURRENT - len(self.trade_manager.active_trades)
                        for signal in signals[:available_slots]:
                            min_priority = MICRO_PUMP_PRIORITY_MIN if (ENABLE_MICRO_PUMP_MODE and signal.is_micro_pump) else 3
                            if signal.priority >= min_priority:
                                if self.trade_manager.open_trade(signal):
                                    await self.notifier.send_explosion_alert(signal, self.trade_manager.active_trades[signal.symbol].capital)
                                    self.total_signals += 1
                                    await asyncio.sleep(1)
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

def start_flask():
    init_database()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

async def main():
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    engine = ExplosionScannerEngine()
    poller = TelegramPoller(TELEGRAM_TOKEN, engine)
    asyncio.create_task(poller.start())
    await engine.run()

if __name__ == "__main__":
    asyncio.run(main())
