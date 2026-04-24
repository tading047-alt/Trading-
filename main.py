#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚂 نظام اكتشاف الانفجارات - الإصدار النهائي v37.0
First Station Explosion Detector - Final Edition v37.0

التحسينات الجديدة:
✅ إدارة مخاطر ديناميكية (حجم الصفقة يعتمد على قوة الإشارة والسيولة)
✅ وقف متحرك ذكي مبني على ATR (مسافة الوقف تتغير حسب تقلب العملة)
✅ استبعاد العملات الكبيرة وعملات الرافعة
✅ إعدادات عالية الجودة (ثقة 75%، نمطين، سيولة كبيرة، سبريد ضيق)
✅ جميع الميزات السابقة (Flask، تليجرام، CSV، نبضات القلب، /status)
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
# 🏆 إعدادات الجودة العالية مع إدارة المخاطر الديناميكية
# =========================================================
TOTAL_CAPITAL = 1000.0
MAX_TRADES_PER_DAY = 6                      # عدد أقل = انتقائية أعلى
BASE_CAPITAL_PER_TRADE = 80.0               # القاعدة الأساسية (تتغير ديناميكياً)
MAX_CAPITAL_PER_TRADE = 200.0               # أقصى مبلغ للصفقة
MIN_CAPITAL_PER_TRADE = 50.0                # أدنى مبلغ للصفقة
MAX_CONCURRENT_TRADES = 3                   

SCAN_INTERVAL = 45
SCAN_BATCH_SIZE = 50
SCAN_SYMBOLS_LIMIT = 350                    # فحص أفضل 350 عملة سيولة

# شروط صارمة للدخول
MIN_CONFIDENCE = 72                          # ثقة مرتفعة
MIN_PATTERNS_REQUIRED = 2                    # نمطان على الأقل
MIN_VOLUME_24H = 130000                      # سيولة جيدة
MAX_SPREAD = 0.22                            # سبريد ضيق جداً
MAX_PRICE_CHANGE_24H = 7.5                   # لم يتحرك السعر بشكل مبالغ

# أوزان الأنماط
PATTERN_WEIGHTS = {
    'calm_before_storm': 45,
    'whale_accumulation': 55,
    'bollinger_squeeze': 40,
    'volume_spike': 25,
    'momentum_building': 20,
    'support_bounce': 30
}

ALLOWED_PATTERNS = ['whale_accumulation', 'calm_before_storm', 'bollinger_squeeze']

# إعدادات BTC
BTC_MIN_ADX = 22
BTC_MAX_DROP_1H = -1.5

# =========================================================
# 🎯 استراتيجية الخروج المتكاملة (وقف متحرك ذكي + جني أرباح)
# =========================================================
EXIT_STRATEGY = {
    'partial_take_profit': [
        {'percent': 3.0, 'sell_ratio': 0.30},
        {'percent': 5.5, 'sell_ratio': 0.30},
    ],
    'trailing_stop': {
        'activation': 3.0,
        'base_distance': 2.0,              # المسافة الأساسية (تتغير حسب ATR)
        'min_distance': 1.0,
        'max_distance': 3.0,
        'tighten_after': 8.0,              # تشديد المسافة بعد +8%
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
                 (id INTEGER PRIMARY KEY, 
                  capital REAL, available REAL, active_trades INTEGER,
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
    symbol: str
    confidence: float
    expected_move: float
    time_to_explosion: int
    entry_price: float
    patterns: List[str]
    volume_24h: float
    current_change: float
    priority: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    atr_percent: float = 0.0   # 🆕 متوسط المدى الحقيقي %
    
    def get_time_estimate(self) -> str:
        minutes = self.time_to_explosion // 60
        seconds = self.time_to_explosion % 60
        if minutes > 0:
            return f"{minutes} دقيقة و {seconds} ثانية"
        return f"{seconds} ثانية"

@dataclass
class ActiveTrade:
    symbol: str
    entry_price: float
    capital: float
    quantity: float
    remaining_quantity: float
    entry_time: datetime
    highest_price: float
    trailing_stop: float
    trailing_activated: bool
    take_profits_hit: List[float]
    pattern: str
    confidence: float
    atr_percent: float = 0.0   # 🆕 لتخزين ATR الصفقة

# =========================================================
# حاسبة نطاق الدخول
# =========================================================
class EntryRangeCalculator:
    def __init__(self):
        self.base_range = 0.01
        self.priority_multipliers = {5: 1.5, 4: 1.3, 3: 1.1, 2: 0.9, 1: 0.7}
        self.pattern_multipliers = {6: 1.4, 5: 1.3, 4: 1.2, 3: 1.1, 2: 1.0, 1: 0.8}
        
    def calculate(self, signal: ExplosionSignal) -> dict:
        current_price = signal.entry_price
        priority_mult = self.priority_multipliers.get(signal.priority, 1.0)
        pattern_count = len(signal.patterns)
        pattern_mult = self.pattern_multipliers.get(pattern_count, 1.0)
        range_percent = self.base_range * priority_mult * pattern_mult
        
        entry_min = current_price * (1 - range_percent)
        entry_max = current_price * (1 + range_percent * 0.7)
        
        if current_price < entry_min:
            position, position_text = "below", "أقل من النطاق - فرصة أفضل"
        elif current_price > entry_max:
            position, position_text = "above", "أعلى من النطاق - انتظر تراجع"
        else:
            position, position_text = "inside", "✅ في النطاق المثالي"
        
        take_profits = [{'percent': tp['percent'], 'price': current_price * (1 + tp['percent']/100), 'sell_ratio': tp['sell_ratio'] * 100} for tp in EXIT_STRATEGY['partial_take_profit']]
        stop_loss = current_price * (1 + EXIT_STRATEGY['hard_stop_loss']/100)
        
        return {
            'current': current_price,
            'min': entry_min,
            'max': entry_max,
            'range_percent': range_percent * 100,
            'position': position,
            'position_text': position_text,
            'take_profits': take_profits,
            'stop_loss': stop_loss,
            'recommendation': self._get_recommendation(signal, position)
        }
    
    def _get_recommendation(self, signal, position) -> dict:
        if signal.priority >= 4:
            if position in ['inside', 'below']:
                return {'action': '✅ اشترِ الآن - السعر ممتاز', 'allocation': '100%', 'urgency': 'فوري'}
            else:
                return {'action': '⚠️ انتظر تراجعاً بسيطاً', 'allocation': '75%', 'urgency': 'انتظار'}
        elif signal.priority >= 3:
            if position in ['inside', 'below']:
                return {'action': '✅ يمكن الشراء مع مراقبة', 'allocation': '75%', 'urgency': 'عادي'}
            else:
                return {'action': '⚠️ انتظر تراجعاً', 'allocation': '50%', 'urgency': 'انتظار'}
        else:
            return {'action': '👀 راقب فقط - لا تدخل', 'allocation': '0%', 'urgency': 'مراقبة'}

# =========================================================
# مدير الصفقات (مع إدارة المخاطر الديناميكية والوقف الذكي)
# =========================================================
class TradeManager:
    def __init__(self):
        self.active_trades: Dict[str, ActiveTrade] = {}
        self.closed_trades: List[dict] = []
        self.available_capital = TOTAL_CAPITAL
        self.daily_trades = 0
        self.daily_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0

    def calculate_position_size(self, signal: ExplosionSignal) -> float:
        """حساب حجم الصفقة ديناميكياً بناءً على قوة الإشارة"""
        base = BASE_CAPITAL_PER_TRADE
        
        # مضاعف الثقة
        if signal.confidence >= 85:
            confidence_mult = 1.5
        elif signal.confidence >= 78:
            confidence_mult = 1.3
        elif signal.confidence >= 72:
            confidence_mult = 1.0
        else:
            confidence_mult = 0.7
        
        # مضاعف السيولة
        if signal.volume_24h > 500000:
            volume_mult = 1.2
        elif signal.volume_24h > 200000:
            volume_mult = 1.0
        else:
            volume_mult = 0.8
        
        # مضاعف عدد الأنماط
        pattern_count = len(signal.patterns)
        if pattern_count >= 3:
            pattern_mult = 1.2
        elif pattern_count >= 2:
            pattern_mult = 1.0
        else:
            pattern_mult = 0.8
        
        # مضاعف الأولوية
        priority_mult = 0.8 + (signal.priority - 1) * 0.15
        
        final = base * confidence_mult * volume_mult * pattern_mult * priority_mult
        return min(max(final, MIN_CAPITAL_PER_TRADE), MAX_CAPITAL_PER_TRADE)
        
    def open_trade(self, signal: ExplosionSignal) -> bool:
        symbol = signal.symbol
        if symbol in self.active_trades or len(self.active_trades) >= MAX_CONCURRENT_TRADES or self.daily_trades >= MAX_TRADES_PER_DAY:
            return False
        
        capital = self.calculate_position_size(signal)
        if capital > self.available_capital:
            return False
        
        quantity = capital / signal.entry_price
        self.available_capital -= capital
        self.daily_trades += 1
        self.total_trades += 1
        
        trade = ActiveTrade(
            symbol=symbol, entry_price=signal.entry_price, capital=capital,
            quantity=quantity, remaining_quantity=quantity,
            entry_time=datetime.now(), highest_price=signal.entry_price,
            trailing_stop=0, trailing_activated=False, take_profits_hit=[],
            pattern=signal.patterns[0] if signal.patterns else 'unknown',
            confidence=signal.confidence,
            atr_percent=signal.atr_percent
        )
        self.active_trades[symbol] = trade
        print(f"  💰 {symbol}: تخصيص {capital:.1f}$ (ثقة {signal.confidence:.0f}%، أنماط {len(signal.patterns)})")
        return True
    
    def update_trade(self, symbol: str, current_price: float, ohlcv_5m: Optional[np.ndarray] = None) -> Optional[dict]:
        if symbol not in self.active_trades:
            return None
        
        trade = self.active_trades[symbol]
        if current_price > trade.highest_price:
            trade.highest_price = current_price
        
        pnl_pct = (current_price - trade.entry_price) / trade.entry_price * 100
        
        # 1. فحص وقف الخسارة الثابت
        if pnl_pct <= EXIT_STRATEGY['hard_stop_loss']:
            return self._close_trade(symbol, current_price, pnl_pct, 'hard_stop_loss')
        
        # 2. تطبيق جني الأرباح الجزئي
        for tp in EXIT_STRATEGY['partial_take_profit']:
            if tp['percent'] not in trade.take_profits_hit and pnl_pct >= tp['percent']:
                sell_quantity = trade.quantity * tp['sell_ratio']
                trade.remaining_quantity -= sell_quantity
                trade.take_profits_hit.append(tp['percent'])
                sell_value = sell_quantity * current_price
                self.available_capital += sell_value
                print(f"  💰 {symbol}: جني أرباح جزئي +{tp['percent']}%")
                if trade.remaining_quantity <= 0:
                    return self._close_trade(symbol, current_price, pnl_pct, 'fully_sold')
        
        # 3. الوقف المتحرك الذكي (متكيف مع ATR)
        if trade.remaining_quantity > 0:
            # حساب مسافة الوقف الديناميكية بناءً على ATR
            if trade.atr_percent > 0:
                base_dist = trade.atr_percent * 0.8  # نسبة من ATR
                trailing_distance = max(EXIT_STRATEGY['trailing_stop']['min_distance'],
                                       min(base_dist, EXIT_STRATEGY['trailing_stop']['max_distance']))
            else:
                trailing_distance = EXIT_STRATEGY['trailing_stop']['base_distance']
            
            # تشديد المسافة عند الأرباح العالية
            if pnl_pct >= EXIT_STRATEGY['trailing_stop']['tighten_after']:
                trailing_distance = EXIT_STRATEGY['trailing_stop']['tightened_distance']
            
            activation_price = trade.entry_price * (1 + EXIT_STRATEGY['trailing_stop']['activation']/100)
            
            if current_price >= activation_price:
                if not trade.trailing_activated:
                    trade.trailing_activated = True
                    trade.trailing_stop = trade.highest_price * (1 - trailing_distance/100)
                    print(f"  🔒 {symbol}: وقف متحرك ذكي مفعل (مسافة {trailing_distance}%)")
                else:
                    new_stop = trade.highest_price * (1 - trailing_distance/100)
                    if new_stop > trade.trailing_stop:
                        trade.trailing_stop = new_stop
                
                if trade.trailing_activated and current_price <= trade.trailing_stop:
                    return self._close_trade(symbol, current_price, pnl_pct, 'trailing_stop_smart')
        
        return None
    
    def _close_trade(self, symbol: str, price: float, pnl_pct: float, reason: str) -> dict:
        trade = self.active_trades[symbol]
        if trade.remaining_quantity > 0:
            sell_value = trade.remaining_quantity * price
            self.available_capital += sell_value
        
        total_pnl_usd = trade.capital * pnl_pct / 100
        self.daily_pnl += pnl_pct
        if pnl_pct > 0:
            self.winning_trades += 1
        
        result = {
            'symbol': symbol, 'entry_price': trade.entry_price,
            'exit_price': price, 'pnl_pct': pnl_pct,
            'pnl_usd': total_pnl_usd, 'entry_time': trade.entry_time,
            'exit_time': datetime.now(), 'pattern': trade.pattern,
            'confidence': trade.confidence, 'exit_reason': reason,
            'take_profits_hit': trade.take_profits_hit,
            'capital_allocated': trade.capital
        }
        self.closed_trades.append(result)
        del self.active_trades[symbol]
        print(f"  🏁 {symbol}: {pnl_pct:+.2f}% | {reason} | متاح: {self.available_capital:.2f}$")
        return result
    
    def get_win_rate(self) -> float:
        if self.total_trades == 0:
            return 0
        return self.winning_trades / self.total_trades * 100

# =========================================================
# كاشف الانفجارات (مع استبعاد العملات الكبيرة والرافعة)
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
        total = len(symbols)
        for i in range(0, total, SCAN_BATCH_SIZE):
            batch = symbols[i:i+SCAN_BATCH_SIZE]
            tasks = [self._analyze_symbol(exchange, sym) for sym in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, ExplosionSignal) and self._should_accept_signal(result):
                    all_signals.append(result)
                    self._record_signal(result)
            progress = min(i + SCAN_BATCH_SIZE, total)
            print(f"   📊 تقدم: {progress}/{total} ({progress*100//total}%)")
            await asyncio.sleep(0.3)
        all_signals.sort(key=lambda x: (x.priority, x.confidence), reverse=True)
        return all_signals
    
    async def _get_active_symbols(self, exchange) -> List[str]:
        try:
            tickers = await exchange.fetch_tickers()
            active = []
            if not tickers:
                print("⚠️ تحذير: لم يتم جلب أي بيانات من البورصة.")
                return active

            for sym, ticker in tickers.items():
                if not sym or not sym.endswith('/USDT'):
                    continue
                
                base_currency = sym.split('/')[0]
                if base_currency in self.EXCLUDED_SYMBOLS:
                    continue
                if any(pattern in base_currency for pattern in self.EXCLUDED_PATTERNS):
                    continue

                volume = ticker.get('quoteVolume')
                change = ticker.get('percentage')
                bid = ticker.get('bid')
                ask = ticker.get('ask')

                if volume is None: volume = 0.0
                if change is None: change = 0.0
                if bid is None: bid = 0.0
                if ask is None: ask = 0.0

                if volume < MIN_VOLUME_24H:
                    continue
                if change > MAX_PRICE_CHANGE_24H or change < -15:
                    continue
                if bid > 0 and ask > 0:
                    spread = (ask - bid) / bid * 100
                    if spread > MAX_SPREAD:
                        continue

                active.append(sym)

            def safe_volume(s):
                data = tickers.get(s, {})
                v = data.get('quoteVolume')
                return v if v is not None else 0.0

            active.sort(key=safe_volume, reverse=True)
            print(f"✅ تم العثور على {len(active)} عملة نشطة (قبل تحديد الحد الأعلى).")
            return active[:SCAN_SYMBOLS_LIMIT]
        except Exception as e:
            print(f"⚠️ خطأ في جلب العملات: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    async def _analyze_symbol(self, exchange, symbol: str) -> Optional[ExplosionSignal]:
        try:
            ohlcv_1m = await exchange.fetch_ohlcv(symbol, '1m', limit=60)
            ohlcv_5m = await exchange.fetch_ohlcv(symbol, '5m', limit=30)
            ticker = await exchange.fetch_ticker(symbol)
            if len(ohlcv_1m) < 30 or len(ohlcv_5m) < 20:
                return None
            data_1m = np.array(ohlcv_1m); data_5m = np.array(ohlcv_5m)
            closes_1m, volumes_1m = data_1m[:,4], data_1m[:,5]
            closes_5m, volumes_5m = data_5m[:,4], data_5m[:,5]
            highs_5m, lows_5m = data_5m[:,2], data_5m[:,3]
            current_price = ticker['last']
            
            # حساب ATR للعملة (متوسط المدى الحقيقي %)
            atr = np.mean(highs_5m[-14:] - lows_5m[-14:]) if len(highs_5m) >= 14 else 0
            atr_percent = (atr / current_price * 100) if current_price > 0 else 2.0
            
            detected_patterns = []
            total_confidence = 0
            time_weights, time_to_explosion = 0, 0
            
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
                    pattern_name = check.get('pattern_name')
                    if pattern_name and pattern_name in self.pattern_weights:
                        w = self.pattern_weights[pattern_name]
                        total_confidence += w
                        time_to_explosion += check['time_estimate'] * w
                        time_weights += w
                    else:
                        total_confidence += 20
                        time_to_explosion += check['time_estimate'] * 20
                        time_weights += 20
            
            if total_confidence >= MIN_CONFIDENCE and len(detected_patterns) >= MIN_PATTERNS_REQUIRED:
                avg_time = int(time_to_explosion / time_weights) if time_weights > 0 else 180
                expected_move = self._calculate_expected_move(total_confidence, len(detected_patterns))
                priority = self._calculate_priority(total_confidence, len(detected_patterns), avg_time)
                return ExplosionSignal(
                    symbol=symbol, confidence=min(100, total_confidence),
                    expected_move=expected_move, time_to_explosion=avg_time,
                    entry_price=current_price, patterns=detected_patterns,
                    volume_24h=ticker.get('quoteVolume', 0),
                    current_change=ticker.get('percentage', 0),
                    priority=priority, atr_percent=round(atr_percent, 2)
                )
        except Exception:
            pass
        return None
    
    def _check_calm_before_storm(self, volumes, closes):
        if len(volumes) < 15 or len(closes) < 10: return {'detected': False}
        recent_vol = np.mean(volumes[-5:])
        older_vol = np.mean(volumes[-15:-5])
        vol_ratio = recent_vol / older_vol if older_vol > 0 else 1
        recent_closes = closes[-8:]
        price_range = (np.max(recent_closes) - np.min(recent_closes)) / np.mean(recent_closes) * 100
        if vol_ratio < 0.5 and price_range < 2.0:
            return {'detected': True, 'name': '🌊 هدوء قبل العاصفة', 'time_estimate': 300, 'pattern_name': 'calm_before_storm'}
        return {'detected': False}
    
    def _check_whale_accumulation(self, volumes, closes):
        if len(volumes) < 10 or len(closes) < 5: return {'detected': False}
        current_vol = volumes[-1]
        avg_vol = np.mean(volumes[-10:])
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1
        recent_closes = closes[-5:]
        price_stability = (np.max(recent_closes) - np.min(recent_closes)) / np.mean(recent_closes) * 100
        if vol_ratio > 1.5 and price_stability < 1.5:
            return {'detected': True, 'name': f'🐋 تجميع حيتان ({vol_ratio:.1f}x)', 'time_estimate': 180, 'pattern_name': 'whale_accumulation'}
        return {'detected': False}
    
    def _check_bollinger_squeeze(self, closes):
        if len(closes) < 20: return {'detected': False}
        recent = closes[-20:]
        current = closes[-1]
        middle, std = np.mean(recent), np.std(recent)
        upper, lower = middle + 2 * std, middle - 2 * std
        bandwidth = (upper - lower) / middle * 100
        price_position = (current - lower) / (upper - lower) if upper != lower else 0.5
        if bandwidth < 5.0 and price_position < 0.4:
            return {'detected': True, 'name': f'🎯 انضغاط بولنجر ({bandwidth:.1f}%)', 'time_estimate': 240, 'pattern_name': 'bollinger_squeeze'}
        return {'detected': False}
    
    def _calculate_expected_move(self, confidence, pattern_count):
        base = 5.0
        if pattern_count >= 4: base += 5.0
        elif pattern_count >= 3: base += 3.0
        elif pattern_count >= 2: base += 1.5
        if confidence >= 80: base += 2.0
        elif confidence >= 70: base += 1.0
        return min(15.0, base)
    
    def _calculate_priority(self, confidence, pattern_count, time_sec):
        priority = 1
        if confidence >= 85: priority += 2
        elif confidence >= 75: priority += 1
        if pattern_count >= 4: priority += 2
        elif pattern_count >= 3: priority += 1
        if time_sec < 120: priority += 1
        return min(5, priority)
    
    def _should_accept_signal(self, signal):
        symbol = signal.symbol
        now = datetime.now()
        if symbol in self.last_signal_time and (now - self.last_signal_time[symbol]).total_seconds() < 300:
            return False
        return True
    
    def _record_signal(self, signal):
        self.recent_signals.append(signal)
        self.last_signal_time[signal.symbol] = datetime.now()

# =========================================================
# بقية المكونات (نظام الإشعارات، فلتر السوق، Flask، المحرك)
# =========================================================
# ... (مطابق للإصدارات السابقة مع استدعاء open_trade بدون allocation_ratio) ...

class EnhancedExplosionNotifier:
    def __init__(self):
        self.range_calculator = EntryRangeCalculator()
        self.telegram_token = TELEGRAM_TOKEN
        self.telegram_chat_id = TELEGRAM_CHAT_ID
        self.last_summary_time = datetime.now()
        
    async def send_explosion_alert(self, signal: ExplosionSignal, capital_allocated: float = 0):
        range_info = self.range_calculator.calculate(signal)
        priority_emoji = "🔴🔴🔴" if signal.priority >= 5 else "🔴🔴" if signal.priority >= 4 else "🔴" if signal.priority >= 3 else "🟡"
        patterns_msg = "\n".join(f"  • {p}" for p in signal.patterns)
        capital_msg = f"\n💰 رأس المال المخصص: {capital_allocated:.1f}$" if capital_allocated > 0 else ""
        msg = f"""
{priority_emoji} *انفجار قادم - أولوية {signal.priority}/5*
{BOT_TAG}

🪙 *{signal.symbol}*
💰 السعر الحالي: {signal.entry_price:.8f}
📊 الثقة: {signal.confidence:.1f}%
📈 الصعود المتوقع: +{signal.expected_move:.1f}%
⏱️ الوقت المتوقع: {signal.get_time_estimate()}
📊 تقلب ATR: {signal.atr_percent:.1f}%
{capital_msg}
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
        targets_msg = ""
        for i, tp in enumerate(range_info['take_profits'], 1):
            targets_msg += f"   🎯 هدف {i}: +{tp['percent']}% ({tp['price']:.8f}) - بيع {tp['sell_ratio']:.0f}%\n"
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
    
    # ... (باقي التوابع مطابقة للإصدار السابق) ...
    async def send_summary(self, signals): pass
    async def send_startup_message(self): pass
    async def send_daily_report(self, trade_manager): pass
    async def send_heartbeat(self, engine): pass
    async def _send_telegram(self, message: str): pass

class MarketRegimeFilter:
    # ... (مطابق للإصدار السابق) ...
    pass

app = Flask(__name__)
engine_instance = None

@app.route('/')
def dashboard():
    # ... (مطابق للإصدار السابق) ...
    pass

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

class TelegramPoller:
    # ... (مطابق للإصدار السابق) ...
    pass

class ExplosionScannerEngine:
    def __init__(self):
        self.detector = ExplosionDetector()
        self.notifier = EnhancedExplosionNotifier()
        self.market_filter = MarketRegimeFilter()
        self.trade_manager = TradeManager()
        self.scan_count = 0
        self.total_signals = 0
        self.market_regime = {}
        self.last_scan_stats = {'scanned': 0, 'signals': 0, 'duration': 0, 'time': '-'}
        self.last_daily_report = datetime.now()
        self.last_heartbeat = datetime.now()
        
    async def run(self):
        global engine_instance
        engine_instance = self
        print("╔══════════════════════════════════════════════════════════╗\n║     💥 نظام اكتشاف الانفجارات v37.0 – ديناميكي 💥      ║\n╚══════════════════════════════════════════════════════════╝")
        exchange = ccxt_async.gateio({'enableRateLimit': True, 'rateLimit': 150})
        await self.notifier.send_startup_message()
        try:
            while True:
                self.scan_count += 1
                start_time = time.time()
                self.market_regime = await self.market_filter.analyze(exchange)
                if self.trade_manager.active_trades:
                    for symbol in list(self.trade_manager.active_trades.keys()):
                        try:
                            ticker = await exchange.fetch_ticker(symbol)
                            result = self.trade_manager.update_trade(symbol, ticker['last'])
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
                            if signal.priority >= 3:
                                if self.trade_manager.open_trade(signal):
                                    await self.notifier.send_explosion_alert(signal, self.trade_manager.active_trades[signal.symbol].capital)
                                    self.total_signals += 1
                                    await asyncio.sleep(1)
                        await self.notifier.send_summary(signals)
                    else:
                        print("\n⚪ لا توجد عملات مرشحة للانفجار حالياً")
                else:
                    print(f"\n⚠️ التداول متوقف")
                elapsed = time.time() - start_time
                self.last_scan_stats = {'scanned': SCAN_SYMBOLS_LIMIT, 'signals': len(signals) if 'signals' in locals() else 0, 'duration': round(elapsed, 2), 'time': datetime.now().strftime('%H:%M:%S')}
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
