#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚂 نظام اكتشاف الانفجارات - V40.1 (أوامر وإشعارات ثابتة)
First Station Explosion Detector - Stable Commands Edition
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
BOT_TAG = "#Exp100"

# =========================================================
# وضع الصيد المفتوح (لجمع البيانات)
# =========================================================
MAX_TRADES_PER_DAY = 999
MAX_CONCURRENT_TRADES = 10
TOTAL_CAPITAL = 1000.0
CAPITAL_PER_TRADE = 50.0
SCAN_INTERVAL = 30
SCAN_BATCH_SIZE = 100
SCAN_SYMBOLS_LIMIT = 500
MIN_CONFIDENCE = 40
MIN_PATTERNS_REQUIRED = 1
MIN_VOLUME_24H = 20000
MAX_SPREAD = 0.8
MAX_PRICE_CHANGE_24H = 15.0

ALLOWED_PATTERNS = ['whale_accumulation', 'calm_before_storm', 'bollinger_squeeze',
                    'volume_spike', 'momentum_building', 'support_bounce', 'micro_pump', 'micro_breakout']

PATTERN_WEIGHTS = {
    'calm_before_storm': 45, 'whale_accumulation': 55, 'bollinger_squeeze': 40,
    'volume_spike': 25, 'momentum_building': 20, 'support_bounce': 30,
    'micro_pump': 90, 'micro_breakout': 80
}

ENABLE_MICRO_PUMP_MODE = True
MICRO_PUMP_CAPITAL_PER_TRADE = 15.0
MICRO_PUMP_MIN_VOLUME_24H = 10000
MICRO_PUMP_MAX_PRICE = 0.005
MICRO_PUMP_MIN_VOLUME_RATIO = 2.0
MICRO_PUMP_MIN_PRICE_CHANGE_1M = 1.5
MICRO_PUMP_MAX_SPREAD = 0.9
MICRO_PUMP_TAKE_PROFIT = 8.0
MICRO_PUMP_STOP_LOSS = -3.0
MICRO_PUMP_TRAILING_ACTIVATION = 2.0
MICRO_PUMP_TRAILING_DISTANCE = 1.5

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

# =========================================================
# مدير الصفقات (مع إشعارات الإغلاق وتسجيل قاعدة البيانات)
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
        max_con = MAX_CONCURRENT_TRADES
        if signal.is_micro_pump: max_con = MICRO_PUMP_MAX_CONCURRENT
        if len(self.active_trades) >= max_con: return False, 0.0
        capital = MICRO_PUMP_CAPITAL_PER_TRADE if signal.is_micro_pump else CAPITAL_PER_TRADE
        if capital > self.available_capital: return False, 0.0
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
        print(f"  ✅ {symbol}: دخول ناجح! الثقة={signal.confidence:.0f}% | المبلغ={capital:.1f}$")
        return True, capital

    def update_trade(self, symbol: str, current_price: float, ohlcv_5m: Optional[np.ndarray] = None) -> Optional[dict]:
        if symbol not in self.active_trades: return None
        trade = self.active_trades[symbol]
        if current_price > trade.highest_price: trade.highest_price = current_price
        pnl_pct = (current_price - trade.entry_price) / trade.entry_price * 100

        if trade.is_micro_pump:
            if pnl_pct <= MICRO_PUMP_STOP_LOSS:
                return self._close_trade(symbol, current_price, pnl_pct, 'micro_pump_stop_loss')
            if pnl_pct >= MICRO_PUMP_TAKE_PROFIT:
                return self._close_trade(symbol, current_price, pnl_pct, 'micro_pump_take_profit')
            if pnl_pct >= MICRO_PUMP_TRAILING_ACTIVATION:
                new_stop = current_price * (1 - MICRO_PUMP_TRAILING_DISTANCE/100)
                if not trade.trailing_activated:
                    trade.trailing_activated = True
                    trade.trailing_stop = new_stop
                elif new_stop > trade.trailing_stop:
                    trade.trailing_stop = new_stop
                if trade.trailing_activated and current_price <= trade.trailing_stop:
                    return self._close_trade(symbol, current_price, pnl_pct, 'micro_pump_trailing_stop')
            return None

        if pnl_pct <= EXIT_STRATEGY['hard_stop_loss']:
            return self._close_trade(symbol, current_price, pnl_pct, 'hard_stop_loss')
        for tp in EXIT_STRATEGY['partial_take_profit']:
            if tp['percent'] not in trade.take_profits_hit and pnl_pct >= tp['percent']:
                sell_q = trade.quantity * tp['sell_ratio']
                trade.remaining_quantity -= sell_q
                trade.take_profits_hit.append(tp['percent'])
                self.available_capital += sell_q * current_price
                if trade.remaining_quantity <= 0:
                    return self._close_trade(symbol, current_price, pnl_pct, 'fully_sold')

        if ENABLE_EARLY_EXIT and ohlcv_5m is not None and len(ohlcv_5m) >= 10 and trade.remaining_quantity > 0:
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

        if trade.remaining_quantity > 0:
            trailing_dist = EXIT_STRATEGY['trailing_stop']['base_distance']
            if pnl_pct >= EXIT_STRATEGY['trailing_stop']['tighten_after']:
                trailing_dist = EXIT_STRATEGY['trailing_stop']['tightened_distance']
            activation_price = trade.entry_price * (1 + EXIT_STRATEGY['trailing_stop']['activation']/100)
            if current_price >= activation_price:
                new_stop = current_price * (1 - trailing_dist/100)
                if not trade.trailing_activated:
                    trade.trailing_activated = True
                    trade.trailing_stop = new_stop
                elif new_stop > trade.trailing_stop:
                    trade.trailing_stop = new_stop
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
# كاشف الانفجارات (مع استبعاد العملات الكبيرة والرافعة)
# =========================================================
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

            c1 = self._check_calm_before_storm(volumes_5m, closes_5m)
            c2 = self._check_whale_accumulation(volumes_1m, closes_1m)
            c3 = self._check_bollinger_squeeze(closes_5m)
            for check in [c1, c2, c3]:
                if check['detected']:
                    detected_patterns.append(check['name'])
                    w = self.pattern_weights.get(check.get('pattern_name', ''), 20)
                    total_conf += w; time_exp += check['time_estimate'] * w; time_w += w
            if total_conf >= MIN_CONFIDENCE and len(detected_patterns) >= MIN_PATTERNS_REQUIRED:
                avg_time = int(time_exp / time_w) if time_w else 180
                priority = self._calculate_priority(total_conf, len(detected_patterns), avg_time)
                return ExplosionSignal(symbol=symbol, confidence=min(100, total_conf),
                    expected_move=6.0, time_to_explosion=avg_time, entry_price=current_price,
                    patterns=detected_patterns, volume_24h=ticker.get('quoteVolume',0),
                    current_change=ticker.get('percentage',0),
                    priority=priority, atr_percent=round(atr_percent,2))
        except: return None
        return None

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
    def _check_micro_pump_spike(self, volumes, closes, current_price):
        if len(volumes) < 10 or len(closes) < 2: return {'detected': False}
        avg_vol = np.mean(volumes[-11:-1]) if len(volumes) >= 11 else volumes[-2]
        vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1
        price_change_1m = (closes[-1] - closes[-2]) / closes[-2] * 100
        if (vol_ratio >= MICRO_PUMP_MIN_VOLUME_RATIO and price_change_1m >= MICRO_PUMP_MIN_PRICE_CHANGE_1M and current_price <= MICRO_PUMP_MAX_PRICE):
            return {'detected': True, 'name': f'🐭 Micro Pump ({vol_ratio:.1f}x)', 'time_estimate': 30, 'pattern_name': 'micro_pump'}
        return {'detected': False}
    def _check_micro_breakout(self, highs, closes, volumes, current_price):
        if len(highs) < 15 or len(volumes) < 10: return {'detected': False}
        recent_high = np.max(highs[-16:-1])
        avg_vol = np.mean(volumes[-11:-1]) if len(volumes) >= 11 else volumes[-2]
        vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1
        if closes[-1] > recent_high and vol_ratio >= 2.0 and current_price <= MICRO_PUMP_MAX_PRICE:
            return {'detected': True, 'name': '🚀 Micro Breakout', 'time_estimate': 60, 'pattern_name': 'micro_breakout'}
        return {'detected': False}
    def _calculate_expected_move(self, conf, cnt):
        base=5.0
        if cnt>=4: base+=5.0
        elif cnt>=3: base+=3.0
        elif cnt>=2: base+=1.5
        if conf>=80: base+=2.0
        elif conf>=70: base+=1.0
        return min(15.0, base)
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
# نظام الإشعارات (موثوق)
# =========================================================
class EnhancedExplosionNotifier:
    def __init__(self):
        self.telegram_token = TELEGRAM_TOKEN; self.telegram_chat_id = TELEGRAM_CHAT_ID
    async def send_open_trade_alert(self, signal, capital):
        pat="\n".join(f"  • {p}" for p in signal.patterns)
        msg=f"""🔴 *فتح صفقة جديدة*\n{BOT_TAG}\n\n🪙 *{signal.symbol}*\n💵 السعر: {signal.entry_price:.8f}\n💰 المبلغ: {capital:.2f}$\n📊 الثقة: {signal.confidence:.1f}%\n🎯 الأولوية: {signal.priority}/5\n📋 الأنماط:\n{pat}\n🕐 `{datetime.now().strftime('%H:%M:%S')}`"""
        await self._send_telegram(msg)
    async def send_trade_closed_alert(self, result, available):
        emoji="💰" if result['pnl_pct']>0 else "📉"
        msg=f"""{emoji} *إغلاق صفقة*\n{BOT_TAG}\n\n🪙 {result['symbol']}\n📊 الربح: {result['pnl_pct']:+.2f}% ({result['pnl_usd']:+.2f}$)\n🎯 السبب: {result['exit_reason']}\n💵 الرصيد الحالي: {available:.2f}$\n🕐 `{datetime.now().strftime('%H:%M:%S')}`"""
        await self._send_telegram(msg)
    async def send_startup_message(self):
        msg=f"""🚀 *تم تشغيل نظام الانفجارات V40.1*\n{BOT_TAG}\n✅ *النظام يعمل بنجاح!*\n🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"""
        await self._send_telegram(msg)
    async def send_daily_report(self, tm):
        wr=tm.get_win_rate(); net=tm.available_capital-TOTAL_CAPITAL
        msg=f"""📊 *التقرير اليومي*\n{BOT_TAG}\n🔄 صفقات اليوم: {tm.daily_trades}\n✅ نسبة النجاح: {wr:.1f}%\n💰 صافي الربح: {net:+.2f}$\n🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"""
        await self._send_telegram(msg)
    async def send_heartbeat(self, engine):
        m=engine.market_regime
        msg=f"""💓 *نبضة قلب*\n{BOT_TAG}\n📊 السوق: {m.get('regime','?')}\n🔍 دورات: {engine.scan_count}\n📈 صفقات اليوم: {engine.trade_manager.daily_trades}\n🕐 `{datetime.now().strftime('%H:%M:%S')}`"""
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
# مستمع أوامر تليجرام (معالج محسن جداً)
# =========================================================
class TelegramPoller:
    def __init__(self, token, engine, notifier):
        self.token = token
        self.engine = engine
        self.notifier = notifier
        self.last_update_id = 0

    async def start(self):
        print("🤖 بدء استقبال أوامر تليجرام (الإصدار المحسن)...")
        # إعادة تعيين معرف التحديث لتجنب تجاهل الرسائل القديمة
        try:
            url = f"https://api.telegram.org/bot{self.token}/getUpdates"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params={"offset": -1, "timeout": 2})
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok") and data["result"]:
                        self.last_update_id = data["result"][-1]["update_id"] + 1
                        print(f"  🧹 تم تنظيف {len(data['result'])} تحديث قديم.")
        except Exception:
            pass

        while True:
            try:
                url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                params = {"offset": self.last_update_id + 1, "timeout": 10}
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(url, params=params)
                    if resp.status_code != 200:
                        # طباعة الخطأ لتحليله
                        print(f"  ⚠️ getUpdates فشل: {resp.status_code} - {resp.text[:100]}")
                        await asyncio.sleep(5)
                        continue

                data = resp.json()
                if not data.get("ok"):
                    print(f"  ⚠️ تليجرام ليس OK: {data}")
                    await asyncio.sleep(5)
                    continue

                for upd in data.get("result", []):
                    self.last_update_id = upd["update_id"]
                    message = upd.get("message")
                    if not message or "text" not in message:
                        continue

                    text = message["text"].strip()
                    chat_id = message["chat"]["id"]
                    print(f"  📩 أمر وارد: '{text}' من {chat_id}")

                    if text == "/status":
                        await self._reply_status(chat_id)
                    elif text == "/download":
                        await self.notifier.send_csv_links(chat_id)
                    elif text == "/open":
                        await self._reply_open(chat_id)
                    elif text == "/closed":
                        await self._reply_closed(chat_id)
                    elif text == "/stats":
                        await self._reply_stats(chat_id)
                    elif text == "/help":
                        await self._reply_help(chat_id)
                    else:
                        await self._send_msg(chat_id, "❌ أمر غير معروف. استخدم /help")
                        
            except asyncio.CancelledError:
                print("⏹️ توقف TelegramPoller.")
                break
            except Exception as e:
                print(f"⚠️ خطأ في poller: {e}")
                import traceback
                traceback.print_exc()
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
            can_trade=True
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
# المحرك الرئيسي (مستقر مع معالجة أخطاء شاملة)
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
        print("╔══════════════════════════════════════════════════════════╗\n║     💥 نظام الانفجارات V40.1 – أوامر وإشعارات ثابتة 💥      ║\n╚══════════════════════════════════════════════════════════╝")
        
        while True:
            try:
                exchange = ccxt_async.gateio({'enableRateLimit': True, 'rateLimit': 150})
                await exchange.fetch_ticker('BTC/USDT')
                print("✅ تم الاتصال بالبورصة بنجاح.")
                break
            except Exception as e:
                print(f"❌ فشل الاتصال: {e}. إعادة المحاولة خلال 30 ثانية...")
                await asyncio.sleep(30)

        await self.notifier.send_startup_message()
        
        while True:
            try:
                self.scan_count += 1
                start_time = time.time()
                
                try: self.market_regime = await self.market_filter.analyze(exchange)
                except: self.market_regime = {'can_trade':True}

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
                            if signal.priority >= 1:
                                success, capital = self.trade_manager.open_trade(signal)
                                if success:
                                    await self.notifier.send_open_trade_alert(signal, capital)
                                    self.total_signals += 1
                                    await asyncio.sleep(0.3)
                    else: print("\n⚪ لا توجد إشارات")
                else: print("\n⚠️ التداول متوقف")

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
    <!DOCTYPE html><html dir="rtl"><head><title>نظام الانفجارات V40.1</title><meta charset="utf-8"><meta http-equiv="refresh" content="30">
    <style>body{font-family:Arial;background:#1a1a2e;color:#eee;margin:20px}.card{background:#16213e;border-radius:10px;padding:20px;margin:10px}.badge{padding:5px 10px;border-radius:20px}.success{background:#0f9d58}h1,h2{color:#fff}p{margin:10px 0}</style></head><body>
    <h1>🚂 نظام الانفجارات V40.1 – أوامر وإشعارات ثابتة</h1>
    <div style="display:flex;flex-wrap:wrap">
    <div class="card" style="flex:1"><h2>📊 السوق</h2><p>النظام: {{m.trend}}</p><p>ADX: {{m.adx}} | BTC 1h: {{m.btc_change}}%</p></div>
    <div class="card" style="flex:1"><h2>💰 الحساب</h2><p>الرصيد: ${{"%.2f"|format(tm.available_capital)}}</p><p>نشطة: {{tm.active_trades|length}}</p><p>اليوم: {{tm.daily_trades}}</p><p>نجاح: {{"%.1f"|format(tm.get_win_rate())}}%</p></div>
    <div class="card" style="flex:1"><h2>🔍 آخر مسح</h2><p>العملات: {{s.scanned}}</p><p>الإشارات: {{s.signals}}</p><p>المدة: {{s.duration}} ث</p></div>
    </div>
    <div class="card"><h2>📁 تحميل</h2><a href="/download/signals">📊 الإشارات</a> | <a href="/download/trades">📈 الصفقات</a> | <a href="/download/snapshots">📸 اللقطات</a> | <a href="/download/errors">⚠️ الأخطاء</a></div>
    <p style="text-align:center;opacity:0.7">آخر تحديث: {{now}}</p></body></html>''',
    m=m, s=s, tm=tm, now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/health')
def health(): return jsonify({'status':'healthy'})

@app.route('/download/<ft>')
def download_file(ft):
    files = {'signals':SIGNALS_FILE,'trades':TRADES_FILE,'snapshots':SNAPSHOT_FILE,'errors':ERRORS_FILE}
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
