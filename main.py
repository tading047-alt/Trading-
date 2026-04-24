#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚂 نظام اكتشاف الانفجارات - v38.0 (وضع الصيد المفتوح)
First Station Explosion Detector - Open Season Edition

التعديلات الجذرية لدخول كل الصفقات:
✅ إزالة فلتر الأولوية (يدخل أي إشارة)
✅ ضمان أولوية دنيا للإشارات التي تتجاوز الثقة
✅ سجل تفصيلي يوضح سبب الدخول أو الرفض
✅ إدارة رأس مال معكوسة (مبلغ أكبر للإشارات الضعيفة للاختبار)
✅ تعطيل التكيف مع السوق لضمان ثبات الإعدادات
✅ جميع ميزات الإصدارات السابقة (Micro Pump، خروج مبكر، ...)
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

# 🎯 وضع الصيد المفتوح
MAX_TRADES_PER_DAY = 999
MAX_CONCURRENT_TRADES = 10
TOTAL_CAPITAL = 1000.0
BASE_CAPITAL_PER_TRADE = 75.0
MAX_CAPITAL_PER_TRADE = 150.0
MIN_CAPITAL_PER_TRADE = 30.0

SCAN_INTERVAL = 30
SCAN_BATCH_SIZE = 100
SCAN_SYMBOLS_LIMIT = 500

# 🎯 إعدادات مخففة جداً
MIN_CONFIDENCE = 35                  # دخول بأي ثقة تقريباً
MIN_PATTERNS_REQUIRED = 1
MIN_VOLUME_24H = 20000
MAX_SPREAD = 0.9
MAX_PRICE_CHANGE_24H = 20.0

# السماح بكل شيء
ALLOWED_PATTERNS = ['whale_accumulation', 'calm_before_storm', 'bollinger_squeeze',
                   'volume_spike', 'momentum_building', 'support_bounce', 'micro_pump', 'micro_breakout']

PATTERN_WEIGHTS = {
    'calm_before_storm': 45, 'whale_accumulation': 55, 'bollinger_squeeze': 40,
    'volume_spike': 25, 'momentum_building': 20, 'support_bounce': 30,
    'micro_pump': 90, 'micro_breakout': 80
}

ENABLE_MICRO_PUMP_MODE = True
MICRO_PUMP_CAPITAL_PER_TRADE = 20.0
MICRO_PUMP_MIN_VOLUME_24H = 10000
MICRO_PUMP_MAX_PRICE = 0.005
MICRO_PUMP_MIN_VOLUME_RATIO = 2.0
MICRO_PUMP_MIN_PRICE_CHANGE_1M = 1.5
MICRO_PUMP_MAX_SPREAD = 0.9
MICRO_PUMP_TAKE_PROFIT = 10.0
MICRO_PUMP_STOP_LOSS = -3.5
MICRO_PUMP_TRAILING_ACTIVATION = 2.0
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
    # ... (نفس الكود السابق) ...
    pass
def update_db_status(capital, available, active, daily, win_rate, regime, btc_change):
    # ... (نفس الكود السابق) ...
    pass

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

# --------------------------- تعطيل التكيف مع السوق ---------------------------
def adapt_config_to_market(market_regime: dict):
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
        # 🆕 إدارة معكوسة: الثقة القليلة = مبلغ أكبر للاختبار
        if signal.confidence < 50:
            return min(MAX_CAPITAL_PER_TRADE, BASE_CAPITAL_PER_TRADE * 1.5)
        elif signal.confidence < 70:
            return BASE_CAPITAL_PER_TRADE
        else:
            return max(MIN_CAPITAL_PER_TRADE, BASE_CAPITAL_PER_TRADE * 0.8)

    def open_trade(self, signal: ExplosionSignal) -> bool:
        symbol = signal.symbol
        if symbol in self.active_trades:
            print(f"  ⚠️ {symbol}: مرفوض - صفقة نشطة بالفعل")
            return False
        max_con = MAX_CONCURRENT_TRADES
        if signal.is_micro_pump: max_con = MICRO_PUMP_MAX_CONCURRENT
        if len(self.active_trades) >= max_con:
            print(f"  ⚠️ {symbol}: مرفوض - الحد الأقصى للصفقات المتزامنة ({max_con})")
            return False
        capital = self.calculate_position_size(signal)
        if capital > self.available_capital:
            print(f"  ⚠️ {symbol}: مرفوض - رصيد غير كاف (يحتاج {capital:.1f}$، المتاح {self.available_capital:.1f}$)")
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
        print(f"  ✅ {symbol}: دخول ناجح! الثقة={signal.confidence:.0f}% | الأنماط={len(signal.patterns)} | المبلغ={capital:.1f}$")
        return True

    # ... (باقي دوال update_trade و _close_trade مطابقة للإصدار v37.4) ...
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
                if not trade.trailing_activated:
                    trade.trailing_activated = True
                    trade.trailing_stop = trade.highest_price * (1 - MICRO_PUMP_TRAILING_DISTANCE/100)
                else:
                    new_stop = trade.highest_price * (1 - MICRO_PUMP_TRAILING_DISTANCE/100)
                    if new_stop > trade.trailing_stop: trade.trailing_stop = new_stop
                if trade.trailing_activated and current_price <= trade.trailing_stop:
                    return self._close_trade(symbol, current_price, pnl_pct, 'micro_pump_trailing_stop')
            return None

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

# --------------------------- كاشف الانفجارات (مع ضمان الأولوية) ---------------------------
class ExplosionDetector:
    def __init__(self):
        self.pattern_weights = PATTERN_WEIGHTS
        self.recent_signals = deque(maxlen=500)
        self.last_signal_time = {}
    EXCLUDED_PATTERNS = ['3S', '3L', '5S', '5L', 'X3', 'X5', 'BEAR', 'BULL', 'UP', 'DOWN']
    EXCLUDED_SYMBOLS = ['BTC/USDT', 'ETH/USDT']

    async def scan_market(self, exchange) -> List[ExplosionSignal]:
        # ... (نفس الكود السابق) ...
        pass
    async def _get_active_symbols(self, exchange) -> List[str]:
        # ... (نفس الكود السابق) ...
        pass
    async def _analyze_symbol(self, exchange, symbol: str) -> Optional[ExplosionSignal]:
        # ... (نفس الكود السابق) ...
        pass

    def _calculate_priority(self, conf, cnt, time_sec):
        pri = 1
        # 🆕 ضمان أولوية دنيا: إذا تجاوزت الثقة الحد الأدنى، نحصل على الأقل على 2
        if conf >= MIN_CONFIDENCE:
            pri = max(pri, 2)
        if conf >= 85: pri = max(pri, 3)
        if cnt >= 3: pri = max(pri, 3)
        if time_sec < 120: pri += 1
        return min(5, pri)

    # ... (باقي الدوال مطابقة للإصدار v37.4) ...

# --------------------------- نظام الإشعارات ---------------------------
class EnhancedExplosionNotifier:
    # ... (نفس الكود السابق) ...
    pass

# --------------------------- TelegramPoller ---------------------------
class TelegramPoller:
    # ... (نفس الكود السابق مع أمر /download) ...
    pass

# --------------------------- المحرك الرئيسي (معدل) ---------------------------
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
        print("╔══════════════════════════════════════════════════════════╗\n║     💥 نظام الانفجارات v38.0 – الصيد المفتوح 💥      ║\n╚══════════════════════════════════════════════════════════╝")
        exchange = ccxt_async.gateio({'enableRateLimit': True, 'rateLimit': 150})
        await self.notifier.send_startup_message()
        try:
            while True:
                self.scan_count += 1; start_time = time.time()
                self.market_regime = await self.market_filter.analyze(exchange)
                adapt_config_to_market(self.market_regime)

                # ... (تحديث الصفقات النشطة) ...

                if self.market_regime.get('can_trade', True):
                    signals = await self.detector.scan_market(exchange)
                    if signals:
                        print(f"\n🎯 تم اكتشاف {len(signals)} إشارة!")
                        available_slots = MAX_CONCURRENT_TRADES - len(self.trade_manager.active_trades)
                        opened = 0
                        for signal in signals[:available_slots]:
                            # 🆕 نسمح بأي أولوية
                            if signal.priority >= 1:
                                if self.trade_manager.open_trade(signal):
                                    opened += 1
                                    self.total_signals += 1
                                    await asyncio.sleep(0.3)
                        if opened == 0:
                            print("   ⚠️ لم يتم فتح أي صفقة. تحقق من الرصيد أو حدود الصفقات.")
                    else:
                        print("\n⚪ لا توجد إشارات")
                # ... (باقي الدورة) ...
                await asyncio.sleep(SCAN_INTERVAL)
        except KeyboardInterrupt:
            print("\n⏹️ إيقاف النظام...")
        finally:
            await exchange.close()

# --------------------------- Flask ---------------------------
app = Flask(__name__)
engine_instance = None

# ... (نفس مسارات Flask السابقة) ...

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
