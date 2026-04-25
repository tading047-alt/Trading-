#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚂 نظام اكتشاف الانفجارات - Paper Trading & Backtesting
First Station Explosion Detector - Simulation Edition

المميزات:
✅ محاكاة تداول حقيقي برأس مال افتراضي 500$
✅ Backtesting سريع لآخر 7 أيام مع إشعار تليجرام
✅ تأثير visually على الرصيد الافتراضي
✅ أوامر تليجرام للتحكم
✅ لوحة تحكم ويب
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
# إعدادات تليجرام (تأكد من صحتها)
# =========================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")
BOT_TAG = "#PaperTrading"

# =========================================================
# 🧪 إعدادات المحاكاة
# =========================================================
SIMULATION_CAPITAL = 500.0
MAX_TRADES_PER_DAY = 5
MAX_CONCURRENT_TRADES = 1
CAPITAL_PER_TRADE_RATIO = 0.5
MAX_CAPITAL_PER_TRADE = 300.0
MIN_CAPITAL_PER_TRADE = 30.0

SCAN_INTERVAL = 45
SCAN_BATCH_SIZE = 50
SCAN_SYMBOLS_LIMIT = 100

MIN_CONFIDENCE = 70
MIN_PATTERNS_REQUIRED = 2
MIN_VOLUME_24H = 100000
MAX_SPREAD = 0.3
MAX_PRICE_CHANGE_24H = 10.0

ALLOWED_PATTERNS = ['whale_accumulation', 'calm_before_storm', 'bollinger_squeeze']
PATTERN_WEIGHTS = {'calm_before_storm': 45, 'whale_accumulation': 55, 'bollinger_squeeze': 40}

VOLUME_RATIO_THRESHOLD = 1.3
RSI_MAX = 72
MACD_CONFIRMATION = True

EXIT_STRATEGY = {
    'take_profit': 3.5,
    'partial_sell_ratio': 0.5,
    'hard_stop_loss': -2.0,
    'trailing_stop': {'activation': 2.0, 'distance': 0.5, 'tight_distance': 0.5}
}

ENABLE_EARLY_EXIT = True
EARLY_EXIT_BEARISH_CANDLE_BODY = 1.0
EARLY_EXIT_EMA_FAST = 9
EARLY_EXIT_EMA_SLOW = 21
EARLY_EXIT_BREAK_PREV_LOW = True

LOG_DIR = "paper_trading_logs"
os.makedirs(LOG_DIR, exist_ok=True)
SIGNALS_FILE = f"{LOG_DIR}/signals.csv"
TRADES_FILE = f"{LOG_DIR}/trades.csv"
SNAPSHOT_FILE = f"{LOG_DIR}/snapshots.csv"

# =========================================================
# دوال إرسال تليجرام (مضمونة)
# =========================================================
async def send_telegram_message(text: str):
    """إرسال رسالة إلى تليجرام - دالة مستقلة ومضمونة"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ تليجرام غير مضبوط - لم يتم الإرسال")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text.strip(),
                "parse_mode": "Markdown"
            })
            if response.status_code == 200:
                print("✅ تم الإرسال إلى تليجرام")
                return True
            else:
                print(f"⚠️ فشل الإرسال: {response.status_code}")
                return False
    except Exception as e:
        print(f"❌ خطأ تليجرام: {e}")
        return False


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

@dataclass
class ActiveTrade:
    symbol: str; entry_price: float; capital: float; quantity: float
    remaining_quantity: float; entry_time: datetime; highest_price: float
    trailing_stop: float; trailing_activated: bool; take_profit_hit: bool
    pattern: str; confidence: float; atr_percent: float = 0.0

class TradeManager:
    def __init__(self, initial_capital):
        self.available_capital = initial_capital
        self.active_trades: Dict[str, ActiveTrade] = {}
        self.closed_trades: List[dict] = []
        self.daily_trades = 0; self.total_trades = 0; self.winning_trades = 0
        self.symbol_loss_streak: Dict[str, int] = {}

    def open_trade(self, signal: ExplosionSignal) -> Tuple[bool, float]:
        symbol = signal.symbol
        if symbol in self.active_trades: return False, 0.0
        if len(self.active_trades) >= MAX_CONCURRENT_TRADES: return False, 0.0
        if self.daily_trades >= MAX_TRADES_PER_DAY: return False, 0.0
        
        capital = min(self.available_capital * CAPITAL_PER_TRADE_RATIO, MAX_CAPITAL_PER_TRADE)
        if capital < MIN_CAPITAL_PER_TRADE or capital > self.available_capital: return False, 0.0
        
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
        print(f"  🧪 [ورقي] {symbol}: فتح صفقة بـ {capital:.2f}$")
        
        # إشعار فتح الصفقة
        msg = f"""🔴 *فتح صفقة ورقية*\n{BOT_TAG}\n🪙 *{symbol}*\n💵 {signal.entry_price:.8f}\n💰 {capital:.2f}$\n📊 {signal.confidence:.1f}%\n🕐 `{datetime.now().strftime('%H:%M:%S')}`"""
        asyncio.create_task(send_telegram_message(msg))
        
        return True, capital

    def update_trade(self, symbol: str, current_price: float, ohlcv_5m=None) -> Optional[dict]:
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
        return None

    def _close_trade(self, symbol: str, price: float, pnl_pct: float, reason: str) -> dict:
        trade = self.active_trades[symbol]
        if trade.remaining_quantity > 0:
            self.available_capital += trade.remaining_quantity * price
        pnl_usd = trade.capital * pnl_pct / 100
        if pnl_pct > 0: self.winning_trades += 1
        result = {'symbol': symbol, 'entry_price': trade.entry_price, 'exit_price': price,
                  'pnl_pct': pnl_pct, 'pnl_usd': pnl_usd, 'entry_time': trade.entry_time,
                  'exit_time': datetime.now(), 'pattern': trade.pattern,
                  'confidence': trade.confidence, 'exit_reason': reason,
                  'capital_allocated': trade.capital}
        self.closed_trades.append(result)
        del self.active_trades[symbol]
        print(f"  🧪 [ورقي] {symbol}: {pnl_pct:+.2f}% | {reason} | الرصيد: {self.available_capital:.2f}$")
        
        # إشعار إغلاق الصفقة
        emoji = "💰" if pnl_pct > 0 else "📉"
        msg = f"""{emoji} *إغلاق صفقة ورقية*\n{BOT_TAG}\n🪙 {symbol}\n📊 {pnl_pct:+.2f}% ({pnl_usd:+.2f}$)\n🎯 {reason}\n💵 الرصيد: {self.available_capital:.2f}$\n🕐 `{datetime.now().strftime('%H:%M:%S')}`"""
        asyncio.create_task(send_telegram_message(msg))
        
        return result

    def get_win_rate(self) -> float:
        return (self.winning_trades / self.total_trades * 100) if self.total_trades else 0.0

# =========================================================
# كاشف الانفجارات (مختصر)
# =========================================================
class ExplosionDetector:
    def __init__(self):
        self.pattern_weights = PATTERN_WEIGHTS
        self.recent_signals = deque(maxlen=100)
        self.last_signal_time = {}
    EXCLUDED = ['3S','3L','5S','5L','X3','X5','BEAR','BULL','UP','DOWN','BTC/USDT','ETH/USDT','BNB/USDT']

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
            for sym, ticker in tickers.items():
                if not sym or not sym.endswith('/USDT'): continue
                if any(p in sym for p in self.EXCLUDED): continue
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
            print(f"⚠️ خطأ: {e}")
            return []

    async def _analyze_symbol(self, exchange, symbol: str) -> Optional[ExplosionSignal]:
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, '5m', limit=30)
            ticker = await exchange.fetch_ticker(symbol)
            if len(ohlcv) < 20: return None
            data = np.array(ohlcv); closes = data[:,4]; volumes = data[:,5]
            current_price = ticker['last']
            avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else volumes[-1]
            if volumes[-1] / avg_vol < VOLUME_RATIO_THRESHOLD: return None
            rsi = self._calc_rsi(closes)
            if rsi > RSI_MAX: return None
            macd_l, sig_l, _ = self._calc_macd(closes)
            if MACD_CONFIRMATION and macd_l[-1] <= sig_l[-1]: return None
            
            detected = []; total_conf = 0
            for check in [self._check_calm(closes, volumes), self._check_whale(closes, volumes), self._check_boll(closes)]:
                if check['detected']:
                    detected.append(check['name'])
                    total_conf += self.pattern_weights.get(check.get('pn',''), 20)
            
            if total_conf >= MIN_CONFIDENCE and len(detected) >= MIN_PATTERNS_REQUIRED:
                return ExplosionSignal(symbol=symbol, confidence=min(100,total_conf),
                    expected_move=EXIT_STRATEGY['take_profit'], time_to_explosion=120,
                    entry_price=current_price, patterns=detected,
                    volume_24h=ticker.get('quoteVolume',0), current_change=ticker.get('percentage',0),
                    priority=3 if total_conf>=75 else 2)
        except: return None
        return None

    def _calc_rsi(self, c, p=14):
        if len(c)<p+1: return 50
        d=np.diff(c); g=np.where(d>0,d,0); l=np.where(d<0,-d,0)
        ag=np.mean(g[:p]); al=np.mean(l[:p])
        return 100-(100/(1+ag/al)) if al>0 else 100
    def _calc_macd(self, c, f=12, s=26, sp=9):
        ef=pd.Series(c).ewm(span=f,adjust=False).mean().values
        es=pd.Series(c).ewm(span=s,adjust=False).mean().values
        macd=ef-es; sig=pd.Series(macd).ewm(span=sp,adjust=False).mean().values
        return macd, sig, macd-sig
    def _check_calm(self, c, v):
        if len(v)<15: return {'detected':False}
        r=np.mean(v[-5:])/np.mean(v[-15:-5]) if np.mean(v[-15:-5])>0 else 1
        pr=(np.max(c[-8:])-np.min(c[-8:]))/np.mean(c[-8:])*100
        if r<0.5 and pr<2.0: return {'detected':True,'name':'🌊 هدوء','pn':'calm_before_storm'}
        return {'detected':False}
    def _check_whale(self, c, v):
        if len(v)<10: return {'detected':False}
        r=v[-1]/np.mean(v[-10:]) if np.mean(v[-10:])>0 else 1
        st=(np.max(c[-5:])-np.min(c[-5:]))/np.mean(c[-5:])*100
        if r>1.5 and st<1.5: return {'detected':True,'name':f'🐋 حيتان ({r:.1f}x)','pn':'whale_accumulation'}
        return {'detected':False}
    def _check_boll(self, c):
        if len(c)<20: return {'detected':False}
        rec=c[-20:]; cur=c[-1]; mid=np.mean(rec); std=np.std(rec)
        u=mid+2*std; l=mid-2*std; bw=(u-l)/mid*100; pos=(cur-l)/(u-l) if u!=l else 0.5
        if bw<5.0 and pos<0.4: return {'detected':True,'name':f'🎯 بولنجر ({bw:.1f}%)','pn':'bollinger_squeeze'}
        return {'detected':False}
    def _should_accept_signal(self, signal):
        now=datetime.now()
        if signal.symbol in self.last_signal_time and (now-self.last_signal_time[signal.symbol]).total_seconds()<300: return False
        return True
    def _record_signal(self, signal): self.recent_signals.append(signal); self.last_signal_time[signal.symbol]=datetime.now()

# =========================================================
# 🧪 محرك Backtesting (مع إشعار تليجرام مضمون)
# =========================================================
class BacktestEngine:
    def __init__(self, detector, trade_manager):
        self.detector = detector
        self.trade_manager = trade_manager

    async def run(self, exchange):
        print(f"\n📊 بدء Backtesting لآخر 7 أيام...")
        
        # إشعار بدء الاختبار
        await send_telegram_message(f"📊 *بدء Backtesting*\n{BOT_TAG}\n⏳ جاري الاختبار...")
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        symbols = await self.detector._get_active_symbols(exchange)
        
        total_trades = 0; winning_trades = 0
        best_trade = None; worst_trade = None
        pattern_stats = {}; processed_symbols = 0
        
        for symbol in symbols[:30]:
            try:
                since = exchange.parse8601(start_date.strftime('%Y-%m-%dT00:00:00Z'))
                ohlcv = await exchange.fetch_ohlcv(symbol, '5m', since=since, limit=1000)
                if len(ohlcv) < 100: continue
                processed_symbols += 1
                print(f"🔍 اختبار {symbol}... ({len(ohlcv)} شمعة)")
                
                for i in range(100, len(ohlcv)):
                    current_price = ohlcv[i][4]
                    result = self.trade_manager.update_trade(symbol, current_price)
                    if result:
                        total_trades += 1
                        if result['pnl_pct'] > 0: winning_trades += 1
                        if best_trade is None or result['pnl_pct'] > best_trade['pnl_pct']: best_trade = result
                        if worst_trade is None or result['pnl_pct'] < worst_trade['pnl_pct']: worst_trade = result
                        
                        pattern = result.get('pattern', 'غير معروف')
                        if pattern not in pattern_stats: pattern_stats[pattern] = {'total': 0, 'wins': 0, 'pnl': 0.0}
                        pattern_stats[pattern]['total'] += 1
                        pattern_stats[pattern]['pnl'] += result['pnl_pct']
                        if result['pnl_pct'] > 0: pattern_stats[pattern]['wins'] += 1
                    
                    data = np.array(ohlcv[max(0, i-60):i+1])
                    if len(data) < 30: continue
                    closes = data[:, 4]; volumes = data[:, 5]
                    avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else volumes[-1]
                    if volumes[-1] / avg_vol < VOLUME_RATIO_THRESHOLD: continue
                    
                    detected = []
                    for check in [self.detector._check_calm(closes, volumes),
                                  self.detector._check_whale(closes, volumes),
                                  self.detector._check_boll(closes)]:
                        if check['detected']: detected.append(check['name'])
                    
                    if len(detected) >= MIN_PATTERNS_REQUIRED:
                        signal = ExplosionSignal(symbol=symbol, confidence=80, expected_move=3.5,
                            time_to_explosion=120, entry_price=current_price,
                            patterns=detected, volume_24h=500000, current_change=0, priority=3)
                        self.trade_manager.open_trade(signal)
                        
            except Exception as e: print(f"  ⚠️ خطأ: {e}")
        
        # إغلاق الصفقات المتبقية
        for sym in list(self.trade_manager.active_trades.keys()):
            self.trade_manager._close_trade(sym, 0, -2.0, 'end_of_backtest')
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        net_pnl = self.trade_manager.available_capital - SIMULATION_CAPITAL
        
        # عرض النتائج في Terminal
        print(f"""
╔══════════════════════════════════════════════════════════╗
║              📊 نتائج Backtesting                         ║
╠══════════════════════════════════════════════════════════╣
║  🔄 إجمالي الصفقات: {total_trades}                                  ║
║  ✅ الرابحة: {winning_trades}                                          ║
║  🎯 نسبة النجاح: {win_rate:.1f}%                                 ║
║  💰 صافي الربح: {net_pnl:+.2f}$ ({net_pnl/SIMULATION_CAPITAL*100:+.2f}%)                       ║
╚══════════════════════════════════════════════════════════╝
        """)
        
        # 🆕 إرسال النتائج إلى تليجرام (مضمون)
        best_str = f"🏆 أفضل: {best_trade['symbol']} (+{best_trade['pnl_pct']:.2f}%)" if best_trade else ""
        worst_str = f"💔 أسوأ: {worst_trade['symbol']} ({worst_trade['pnl_pct']:.2f}%)" if worst_trade else ""
        
        msg = f"""📊 *نتائج Backtesting*
{BOT_TAG}

🔄 إجمالي الصفقات: {total_trades}
✅ الصفقات الرابحة: {winning_trades}
❌ الصفقات الخاسرة: {total_trades - winning_trades}
🎯 نسبة النجاح: {win_rate:.1f}%
💰 صافي الربح: {net_pnl:+.2f}$ ({net_pnl/SIMULATION_CAPITAL*100:+.2f}%)
{best_str}
{worst_str}

🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
"""
        await send_telegram_message(msg)
        
        # إعادة تعيين الرصيد للتداول الورقي المباشر
        self.trade_manager.available_capital = SIMULATION_CAPITAL
        self.trade_manager.total_trades = 0
        self.trade_manager.winning_trades = 0
        self.trade_manager.closed_trades = []
        self.trade_manager.active_trades = {}
        self.trade_manager.daily_trades = 0

# =========================================================
# 🧪 التداول الورقي المباشر
# =========================================================
class PaperTradingEngine:
    def __init__(self, detector, trade_manager):
        self.detector = detector
        self.trade_manager = trade_manager
        self.scan_count = 0

    async def run(self, exchange):
        print(f"""
╔══════════════════════════════════════════════════════════╗
║     🧪 Paper Trading Live - رأس مال {SIMULATION_CAPITAL}$ 🧪      ║
╚══════════════════════════════════════════════════════════╝
        """)
        await send_telegram_message(f"🚀 *بدء التداول الورقي*\n{BOT_TAG}\n💰 رأس المال: {SIMULATION_CAPITAL}$\n✅ يعمل!")
        
        while True:
            try:
                self.scan_count += 1
                
                if self.trade_manager.active_trades:
                    for symbol in list(self.trade_manager.active_trades.keys()):
                        try:
                            ticker = await exchange.fetch_ticker(symbol)
                            price = ticker['last']
                            self.trade_manager.update_trade(symbol, price)
                        except: pass

                signals = await self.detector.scan_market(exchange)
                if signals:
                    print(f"\n🎯 {len(signals)} إشارة!")
                    for signal in signals[:MAX_CONCURRENT_TRADES]:
                        if signal.priority >= 2:
                            self.trade_manager.open_trade(signal)
                            await asyncio.sleep(0.3)
                else:
                    print("\n⚪ لا توجد إشارات")
                
                print(f"🧪 الرصيد الورقي: {self.trade_manager.available_capital:.2f}$ | الصفقات النشطة: {len(self.trade_manager.active_trades)}")
                await asyncio.sleep(SCAN_INTERVAL)
                
            except Exception as e:
                print(f"❌ خطأ: {e}")
                await asyncio.sleep(30)

# =========================================================
# Flask
# =========================================================
app = Flask(__name__)
engine_instance = None

@app.route('/')
def dashboard():
    if not engine_instance: return "Not ready"
    tm = engine_instance.trade_manager
    return render_template_string('''
    <!DOCTYPE html><html dir="rtl"><head><title>Paper Trading</title><meta charset="utf-8"><meta http-equiv="refresh" content="30">
    <style>body{font-family:Arial;background:#1a1a2e;color:#eee;margin:20px}.card{background:#16213e;border-radius:10px;padding:20px;margin:10px}h1,h2{color:#fff}p{margin:10px 0}</style></head><body>
    <h1>🧪 نظام التداول الورقي – رأس مال 500$</h1>
    <div style="display:flex;flex-wrap:wrap">
    <div class="card" style="flex:1"><h2>💰 الحساب الورقي</h2><p>الرصيد: ${{"%.2f"|format(tm.available_capital)}}</p><p>الصفقات النشطة: {{tm.active_trades|length}}</p><p>صفقات اليوم: {{tm.daily_trades}}</p><p>نسبة النجاح: {{"%.1f"|format(tm.get_win_rate())}}%</p></div>
    <div class="card" style="flex:1"><h2>📊 الأداء العام</h2><p>إجمالي الصفقات: {{tm.total_trades}}</p><p>الصفقات الرابحة: {{tm.winning_trades}}</p></div>
    </div>
    <p style="text-align:center;opacity:0.7">آخر تحديث: {{now}}</p></body></html>''',
    tm=tm, now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/health')
def health(): return jsonify({'status':'healthy'})

def start_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# =========================================================
# الدالة الرئيسية
# =========================================================
async def main():
    # 1. بدء Flask
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    
    # 2. إعداد البورصة
    exchange = ccxt_async.binance({'enableRateLimit': True, 'rateLimit': 200, 'options': {'defaultType': 'spot'}})
    await exchange.fetch_ticker('BTC/USDT')
    print("✅ Binance متصل")
    
    # 3. إعداد المكونات
    detector = ExplosionDetector()
    trade_manager = TradeManager(SIMULATION_CAPITAL)
    
    # 4. تشغيل Backtest أولاً
    print("\n📊 تشغيل Backtest للتقييم...")
    backtest = BacktestEngine(detector, trade_manager)
    await backtest.run(exchange)
    
    # 5. بدء التداول الورقي المباشر
    print("\n🧪 بدء التداول الورقي المباشر...")
    paper_engine = PaperTradingEngine(detector, trade_manager)
    await paper_engine.run(exchange)

if __name__ == "__main__":
    asyncio.run(main())
