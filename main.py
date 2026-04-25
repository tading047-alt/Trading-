#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚂 استراتيجية ذهبية محسنة – Backtesting شهري
"""

import asyncio, pandas as pd, numpy as np, httpx, json, os, time
from datetime import datetime, timedelta
from collections import deque
from typing import Dict, List, Optional, Tuple, Any
import ccxt.async_support as ccxt_async

# =========================================================
# إعدادات تليجرام
# =========================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")
BOT_TAG = "#OptimizedTest"

# =========================================================
# 🎯 العملات المستبعدة
# =========================================================
EXCLUDED_STABLECOINS = ['USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'FDUSD']
EXCLUDED_LARGE_CAPS = ['BTC', 'ETH', 'BNB', 'XRP', 'SOL', 'ADA', 'AVAX', 'DOT']
EXCLUDED_LEVERAGED = ['3S', '3L', '5S', '5L', 'X3', 'X5', 'BEAR', 'BULL', 'UP', 'DOWN']
ALL_EXCLUDED = EXCLUDED_STABLECOINS + EXCLUDED_LARGE_CAPS

def is_excluded(symbol: str) -> bool:
    base = symbol.split('/')[0]
    if base in ALL_EXCLUDED: return True
    if any(lev in base for lev in EXCLUDED_LEVERAGED): return True
    return False

# =========================================================
# 🎯 الإعدادات المحسنة (وسط بين الذهبية والمتوازنة)
# =========================================================
SETTINGS = {
    'MIN_CONFIDENCE': 68,
    'MIN_PATTERNS_REQUIRED': 2,
    'MIN_VOLUME_24H': 100000,
    'MAX_SPREAD': 0.3,
    'TAKE_PROFIT': 3.5,
    'STOP_LOSS': -1.5,
    'TRAILING_ACTIVATION': 1.5,
    'TRAILING_DISTANCE': 0.5,
    'PARTIAL_SELL': True,
    'PARTIAL_SELL_RATIO': 0.5,
    'MIN_VOLUME_RATIO': 1.2,
    'CAPITAL_PER_TRADE_RATIO': 0.1,  # 👈 10% فقط من الرصيد
    'MAX_CAPITAL_PER_TRADE': 100.0,   # 👈 أقصى مبلغ 100$
}

SIMULATION_CAPITAL = 500.0
BACKTEST_DAYS = 30

PATTERN_WEIGHTS = {'calm_before_storm': 45, 'whale_accumulation': 55, 'bollinger_squeeze': 40}
VOLUME_RATIO_THRESHOLD = 1.2
RSI_MAX = 72

# =========================================================
# دوال تليجرام
# =========================================================
async def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text.strip(), "parse_mode": "Markdown"})
    except: pass

# =========================================================
# كاشف مبسط
# =========================================================
class SimpleDetector:
    def __init__(self):
        self.pattern_weights = PATTERN_WEIGHTS

    async def get_symbols(self, exchange, limit=150):
        tickers = await exchange.fetch_tickers()
        active = []
        for sym, t in tickers.items():
            if not sym or not sym.endswith('/USDT'): continue
            if is_excluded(sym): continue
            vol = t.get('quoteVolume') or 0
            if vol < SETTINGS['MIN_VOLUME_24H']: continue
            ch = t.get('percentage') or 0
            if ch > 20 or ch < -10: continue
            bid = t.get('bid') or 0; ask = t.get('ask') or 0
            if bid > 0 and ask > 0 and (ask-bid)/bid*100 > SETTINGS['MAX_SPREAD']: continue
            active.append(sym)
        active.sort(key=lambda s: tickers[s].get('quoteVolume') or 0, reverse=True)
        return active[:limit]

    def analyze(self, ohlcv: np.ndarray) -> Optional[Dict]:
        if len(ohlcv) < 30: return None
        closes = ohlcv[:, 4]; volumes = ohlcv[:, 5]
        
        avg_vol = np.mean(volumes[-20:]) if len(volumes)>=20 else volumes[-1]
        if volumes[-1] / avg_vol < VOLUME_RATIO_THRESHOLD: return None
        
        rsi = self._calc_rsi(closes)
        if rsi > RSI_MAX: return None
        
        detected = []; total_conf = 0
        for check in [self._check_calm(closes, volumes), self._check_whale(closes, volumes), self._check_boll(closes)]:
            if check['detected']:
                detected.append(check['name'])
                total_conf += self.pattern_weights.get(check.get('pn',''), 20)
        
        if total_conf >= SETTINGS['MIN_CONFIDENCE'] and len(detected) >= SETTINGS['MIN_PATTERNS_REQUIRED']:
            return {'confidence': min(100,total_conf), 'patterns': detected, 'entry_price': closes[-1]}
        return None

    def _calc_rsi(self, c, p=14):
        if len(c)<p+1: return 50
        d=np.diff(c); g=np.where(d>0,d,0); l=np.where(d<0,-d,0)
        ag=np.mean(g[:p]); al=np.mean(l[:p])
        return 100-(100/(1+ag/al)) if al>0 else 100
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

# =========================================================
# محاكي محسن (10% لكل صفقة)
# =========================================================
class OptimizedSimulator:
    def __init__(self):
        self.initial_capital = SIMULATION_CAPITAL
        self.capital = SIMULATION_CAPITAL
        self.active = {}
        self.closed = []
        self.total = 0; self.wins = 0
        self.peak_capital = SIMULATION_CAPITAL
        self.max_drawdown = 0.0

    def open_trade(self, entry_price: float, entry_time=None):
        capital = min(self.capital * SETTINGS['CAPITAL_PER_TRADE_RATIO'], SETTINGS['MAX_CAPITAL_PER_TRADE'])
        if capital < 10 or capital > self.capital: return
        self.capital -= capital
        self.total += 1
        self.active['trade'] = {
            'entry': entry_price, 'capital': capital, 'high': entry_price, 'low': entry_price,
            'entry_time': entry_time or datetime.now(), 'trailing': 0, 'activated': False, 'tp_hit': False
        }

    def update(self, price: float, current_time=None):
        current_equity = self.capital + (self.active['trade']['capital'] if 'trade' in self.active else 0)
        if current_equity > self.peak_capital: self.peak_capital = current_equity
        drawdown = (self.peak_capital - current_equity) / self.peak_capital * 100
        if drawdown > self.max_drawdown: self.max_drawdown = drawdown

        if 'trade' not in self.active: return
        t = self.active['trade']
        if price > t['high']: t['high'] = price
        if price < t['low']: t['low'] = price
        pnl = (price - t['entry']) / t['entry'] * 100
        
        if pnl <= SETTINGS['STOP_LOSS']:
            self._close(price, pnl, 'وقف خسارة', current_time)
        elif not t['tp_hit'] and pnl >= SETTINGS['TAKE_PROFIT']:
            t['tp_hit'] = True
            if SETTINGS.get('PARTIAL_SELL', False):
                self.capital += t['capital'] * SETTINGS['PARTIAL_SELL_RATIO'] * (1 + pnl/100)
            t['activated'] = True
            t['trailing'] = price * (1 - SETTINGS['TRAILING_DISTANCE']/100)
        elif pnl >= SETTINGS['TRAILING_ACTIVATION'] and not t['activated']:
            t['activated'] = True
            t['trailing'] = t['high'] * (1 - SETTINGS['TRAILING_DISTANCE']/100)
        
        if t['activated']:
            new_stop = t['high'] * (1 - SETTINGS['TRAILING_DISTANCE']/100)
            if new_stop > t['trailing']: t['trailing'] = new_stop
            if price <= t['trailing']:
                self._close(price, pnl, 'وقف متحرك', current_time)

    def _close(self, price, pnl, reason, current_time=None):
        if 'trade' not in self.active: return
        t = self.active['trade']
        exit_time = current_time or datetime.now()
        self.capital += t['capital'] * (1 + pnl/100)
        if pnl > 0: self.wins += 1
        
        duration = abs((exit_time - t['entry_time']).total_seconds() / 60) if t['entry_time'] and exit_time else 0
        
        self.closed.append({
            'entry': t['entry'], 'exit': price, 'pnl': pnl, 
            'reason': reason, 'capital': t['capital'],
            'duration_minutes': duration
        })
        del self.active['trade']

    def get_stats(self):
        if self.total == 0: 
            return {'total': 0, 'wins': 0, 'win_rate': 0, 'pnl': 0, 'max_drawdown': 0, 
                    'best_trade': None, 'worst_trade': None, 'avg_duration': 0}
        
        net = self.capital - self.initial_capital
        best = max(self.closed, key=lambda x: x['pnl']) if self.closed else None
        worst = min(self.closed, key=lambda x: x['pnl']) if self.closed else None
        avg_duration = np.mean([t['duration_minutes'] for t in self.closed]) if self.closed else 0
        
        return {
            'total': self.total, 'wins': self.wins, 
            'win_rate': self.wins/self.total*100, 'pnl': net,
            'max_drawdown': self.max_drawdown,
            'best_trade': best, 'worst_trade': worst,
            'avg_duration': avg_duration
        }

# =========================================================
# 🚀 الدالة الرئيسية
# =========================================================
async def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║     🧪 استراتيجية ذهبية محسنة – Backtesting شهري 🧪      ║
║     إدارة رأس مال 10% لكل صفقة                           ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    await send_telegram(f"🚀 *بدء اختبار الاستراتيجية المحسنة*\n{BOT_TAG}\n📅 {BACKTEST_DAYS} يوم | 💰 {SIMULATION_CAPITAL}$ | ⚙️ 10% لكل صفقة")
    
    exchange = ccxt_async.binance({'enableRateLimit': True, 'rateLimit': 200, 'options': {'defaultType': 'spot'}})
    await exchange.fetch_ticker('BTC/USDT')
    print("✅ Binance متصل\n")
    
    detector = SimpleDetector()
    simulator = OptimizedSimulator()
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=BACKTEST_DAYS)
    
    symbols = await detector.get_symbols(exchange, limit=150)
    print(f"🪙 العملات المختبرة: {len(symbols)}")
    
    for symbol in symbols:
        try:
            since = exchange.parse8601(start_date.strftime('%Y-%m-%dT00:00:00Z'))
            ohlcv = await exchange.fetch_ohlcv(symbol, '5m', since=since, limit=5000)
            if len(ohlcv) < 100: continue
            
            for i in range(100, len(ohlcv)):
                price = ohlcv[i][4]
                timestamp = datetime.fromtimestamp(ohlcv[i][0]/1000)
                simulator.update(price, timestamp)
                
                data = np.array(ohlcv[max(0,i-60):i+1])
                if len(data) < 30: continue
                
                result = detector.analyze(data)
                if result:
                    simulator.open_trade(price, timestamp)
                    
        except Exception as e: continue
    
    # إغلاق الصفقات المتبقية
    if 'trade' in simulator.active:
        simulator._close(0, -2.0, 'نهاية الاختبار', end_date)
    
    await exchange.close()
    
    stats = simulator.get_stats()
    
    print(f"""
╔══════════════════════════════════════════════════════════╗
║              📊 نتائج Backtesting                         ║
╠══════════════════════════════════════════════════════════╣
║  🔄 الصفقات: {stats['total']}                                          ║
║  ✅ النجاح: {stats['win_rate']:.1f}%                                         ║
║  💰 الربح: {stats['pnl']:+.2f}$ ({stats['pnl']/SIMULATION_CAPITAL*100:+.2f}%)                               ║
║  📉 أقصى انخفاض: {stats['max_drawdown']:.1f}%                                    ║
║  ⏱️ متوسط المدة: {stats['avg_duration']:.0f} دقيقة                                    ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    best_str = f"🏆 أفضل: +{stats['best_trade']['pnl']:.2f}% ({stats['best_trade']['duration_minutes']:.0f}د)" if stats['best_trade'] else ""
    worst_str = f"💔 أسوأ: {stats['worst_trade']['pnl']:.2f}% ({stats['worst_trade']['duration_minutes']:.0f}د)" if stats['worst_trade'] else ""
    
    msg = f"""
📊 *نتائج الاستراتيجية المحسنة*
{BOT_TAG}
🔄 الصفقات: {stats['total']}
✅ النجاح: {stats['win_rate']:.1f}%
💰 الربح: {stats['pnl']:+.2f}$ ({stats['pnl']/SIMULATION_CAPITAL*100:+.2f}%)
📉 أقصى انخفاض: {stats['max_drawdown']:.1f}%
⏱️ متوسط المدة: {stats['avg_duration']:.0f} دقيقة
{best_str}
{worst_str}
🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`
    """
    await send_telegram(msg)

if __name__ == "__main__":
    asyncio.run(main())
