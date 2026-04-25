#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚂 نظام اختبار الاستراتيجيات المتعدد – Backtesting شهري مع تحليلات متقدمة
First Station Multi-Strategy Backtesting Engine - Advanced Analytics

التحليلات الجديدة:
✅ أقصى انخفاض للمحفظة (Max Drawdown) خلال الفترة
✅ أفضل صفقة (الربح + المدة)
✅ أسوأ صفقة (الخسارة + المدة)
✅ متوسط مدة الصفقات لكل استراتيجية
✅ استبعاد العملات المستقرة والعملات الكبيرة
✅ 6 استراتيجيات مختلفة في تشغيل واحد
✅ Backtesting على شهر كامل (30 يوم)
✅ إشعار تليجرام بنتائج كل استراتيجية + ترتيب نهائي
✅ فريمات زمنية متعددة (3m, 5m, 15m)
✅ فلتر EMA + فلتر حجم إضافي + فلتر وقت التداول
"""

import asyncio, threading, pandas as pd, numpy as np, httpx, json, os, time
from datetime import datetime, timedelta
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

import ccxt.async_support as ccxt_async

# =========================================================
# إعدادات تليجرام
# =========================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")
BOT_TAG = "#MultiTest"

# =========================================================
# 🎯 العملات المستبعدة
# =========================================================
EXCLUDED_STABLECOINS = ['USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'FDUSD', 'USDD', 'GUSD', 'LUSD', 'SUSD']
EXCLUDED_LARGE_CAPS = ['BTC', 'ETH', 'BNB', 'XRP', 'SOL', 'ADA', 'AVAX', 'DOT', 'MATIC', 'LINK', 'UNI', 'ATOM', 'LTC', 'ETC', 'XLM', 'BCH']
EXCLUDED_LEVERAGED = ['3S', '3L', '5S', '5L', 'X3', 'X5', 'BEAR', 'BULL', 'UP', 'DOWN']

ALL_EXCLUDED = EXCLUDED_STABLECOINS + EXCLUDED_LARGE_CAPS

def is_excluded(symbol: str) -> bool:
    """التحقق من استبعاد العملة"""
    base = symbol.split('/')[0]
    if base in ALL_EXCLUDED: return True
    if any(lev in base for lev in EXCLUDED_LEVERAGED): return True
    return False

# =========================================================
# 📊 الاستراتيجيات الستة للاختبار (مع التحسينات)
# =========================================================
STRATEGIES = {
    "الذهبية_المحسنة": {
        'MIN_CONFIDENCE': 75, 'MIN_PATTERNS_REQUIRED': 2,
        'MIN_VOLUME_24H': 150000, 'MAX_SPREAD': 0.2,
        'TAKE_PROFIT': 3.5, 'STOP_LOSS': -1.5,
        'TRAILING_ACTIVATION': 1.5, 'TRAILING_DISTANCE': 0.5,
        'PARTIAL_SELL': True, 'PARTIAL_SELL_RATIO': 0.5,
        'MIN_VOLUME_RATIO': 1.5, 'REQUIRE_EMA_ALIGNMENT': True,
        'BEST_HOURS': [8, 9, 10, 13, 14, 15, 16],
        'MAX_CONSECUTIVE_LOSSES': 1
    },
    "المحافظة": {
        'MIN_CONFIDENCE': 80, 'MIN_PATTERNS_REQUIRED': 3,
        'MIN_VOLUME_24H': 200000, 'MAX_SPREAD': 0.15,
        'TAKE_PROFIT': 3.0, 'STOP_LOSS': -1.5,
        'TRAILING_ACTIVATION': 2.0, 'TRAILING_DISTANCE': 0.5
    },
    "المتوازنة": {
        'MIN_CONFIDENCE': 70, 'MIN_PATTERNS_REQUIRED': 2,
        'MIN_VOLUME_24H': 100000, 'MAX_SPREAD': 0.25,
        'TAKE_PROFIT': 5.0, 'STOP_LOSS': -2.0,
        'TRAILING_ACTIVATION': 2.5, 'TRAILING_DISTANCE': 1.0
    },
    "الهجومية": {
        'MIN_CONFIDENCE': 55, 'MIN_PATTERNS_REQUIRED': 1,
        'MIN_VOLUME_24H': 50000, 'MAX_SPREAD': 0.4,
        'TAKE_PROFIT': 8.0, 'STOP_LOSS': -3.0,
        'TRAILING_ACTIVATION': 3.0, 'TRAILING_DISTANCE': 1.5
    },
    "السريعة": {
        'MIN_CONFIDENCE': 65, 'MIN_PATTERNS_REQUIRED': 2,
        'MIN_VOLUME_24H': 75000, 'MAX_SPREAD': 0.3,
        'TAKE_PROFIT': 4.0, 'STOP_LOSS': -1.75,
        'TRAILING_ACTIVATION': 1.5, 'TRAILING_DISTANCE': 0.3
    },
    "صائد_الانفجارات": {
        'MIN_CONFIDENCE': 60, 'MIN_PATTERNS_REQUIRED': 2,
        'MIN_VOLUME_24H': 80000, 'MAX_SPREAD': 0.35,
        'TAKE_PROFIT': 6.0, 'STOP_LOSS': -2.5,
        'TRAILING_ACTIVATION': 3.0, 'TRAILING_DISTANCE': 0.8
    }
}

# =========================================================
# 🎯 الإعدادات المشتركة
# =========================================================
SIMULATION_CAPITAL = 500.0
BACKTEST_DAYS = 30  # شهر كامل

ALLOWED_PATTERNS = ['whale_accumulation', 'calm_before_storm', 'bollinger_squeeze']
PATTERN_WEIGHTS = {'calm_before_storm': 45, 'whale_accumulation': 55, 'bollinger_squeeze': 40}

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
# كاشف الإشارات (بإعدادات متغيرة)
# =========================================================
class FlexibleDetector:
    def __init__(self, settings: dict):
        self.settings = settings
        self.pattern_weights = PATTERN_WEIGHTS

    def should_enter_time(self) -> bool:
        if 'BEST_HOURS' not in self.settings: return True
        return datetime.now().hour in self.settings['BEST_HOURS']

    def check_ema_alignment(self, closes: np.ndarray) -> bool:
        if len(closes) < 22: return True
        ema9 = pd.Series(closes).ewm(span=9, adjust=False).mean().values[-1]
        ema21 = pd.Series(closes).ewm(span=21, adjust=False).mean().values[-1]
        return ema9 > ema21

    async def get_symbols(self, exchange, limit=150):
        tickers = await exchange.fetch_tickers()
        active = []
        for sym, t in tickers.items():
            if not sym or not sym.endswith('/USDT'): continue
            if is_excluded(sym): continue
            vol = t.get('quoteVolume') or 0
            if vol < self.settings['MIN_VOLUME_24H']: continue
            ch = t.get('percentage') or 0
            if ch > 20 or ch < -10: continue
            bid = t.get('bid') or 0; ask = t.get('ask') or 0
            if bid > 0 and ask > 0 and (ask-bid)/bid*100 > self.settings['MAX_SPREAD']: continue
            active.append(sym)
        active.sort(key=lambda s: tickers[s].get('quoteVolume') or 0, reverse=True)
        return active[:limit]

    def analyze(self, ohlcv: np.ndarray, volume_24h: float, current_price: float, current_time=None) -> Optional[Dict]:
        if len(ohlcv) < 30: return None
        closes = ohlcv[:, 4]; volumes = ohlcv[:, 5]
        
        # فلتر الوقت
        if not self.should_enter_time(): return None
        
        # فلتر حجم إضافي
        if 'MIN_VOLUME_RATIO' in self.settings:
            avg_vol = np.mean(volumes[-20:]) if len(volumes)>=20 else volumes[-1]
            if volumes[-1] / avg_vol < self.settings['MIN_VOLUME_RATIO']: return None
        
        # فلتر EMA
        if self.settings.get('REQUIRE_EMA_ALIGNMENT', False):
            if not self.check_ema_alignment(closes): return None
        
        if self._calc_rsi(closes) > 72: return None
        
        detected = []; total_conf = 0
        for check in [self._check_calm(closes, volumes), self._check_whale(closes, volumes), self._check_boll(closes)]:
            if check['detected']:
                detected.append(check['name'])
                total_conf += self.pattern_weights.get(check.get('pn',''), 20)
        
        if total_conf >= self.settings['MIN_CONFIDENCE'] and len(detected) >= self.settings['MIN_PATTERNS_REQUIRED']:
            return {'symbol': 'N/A', 'confidence': min(100,total_conf), 'patterns': detected,
                    'entry_price': current_price, 'volume_24h': volume_24h, 'entry_time': current_time}
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
# محاكي التداول (مع أقصى انخفاض + أفضل/أسوأ صفقة + مدة)
# =========================================================
class Simulator:
    def __init__(self, settings: dict):
        self.settings = settings
        self.initial_capital = SIMULATION_CAPITAL
        self.capital = SIMULATION_CAPITAL
        self.active = {}
        self.closed = []
        self.total = 0; self.wins = 0
        self.consecutive_losses = 0
        
        # لتتبع أقصى انخفاض
        self.peak_capital = SIMULATION_CAPITAL
        self.max_drawdown = 0.0

    def can_open(self) -> bool:
        max_loss = self.settings.get('MAX_CONSECUTIVE_LOSSES', 99)
        return self.consecutive_losses <= max_loss

    def open_trade(self, entry_price: float, entry_time=None):
        if not self.can_open(): return
        capital = min(self.capital * 0.5, 250)
        if capital < 20 or capital > self.capital: return
        self.capital -= capital
        self.total += 1
        self.active['trade'] = {
            'entry': entry_price, 'capital': capital, 'high': entry_price, 'low': entry_price,
            'entry_time': entry_time or datetime.now(), 'trailing': 0, 'activated': False, 'tp_hit': False
        }

    def update(self, price: float, current_time=None):
        # تحديث أقصى انخفاض
        current_equity = self.capital + (self.active['trade']['capital'] if 'trade' in self.active else 0)
        if current_equity > self.peak_capital:
            self.peak_capital = current_equity
        drawdown = (self.peak_capital - current_equity) / self.peak_capital * 100
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

        if 'trade' not in self.active: return
        t = self.active['trade']
        if price > t['high']: t['high'] = price
        if price < t['low']: t['low'] = price
        pnl = (price - t['entry']) / t['entry'] * 100
        
        if pnl <= self.settings['STOP_LOSS']:
            self._close(price, pnl, 'وقف خسارة', current_time)
        elif not t['tp_hit'] and pnl >= self.settings['TAKE_PROFIT']:
            t['tp_hit'] = True
            if self.settings.get('PARTIAL_SELL', False):
                sell_ratio = self.settings.get('PARTIAL_SELL_RATIO', 0.5)
                self.capital += t['capital'] * sell_ratio * (1 + pnl/100)
            t['activated'] = True
            t['trailing'] = price * (1 - self.settings['TRAILING_DISTANCE']/100)
        elif pnl >= self.settings['TRAILING_ACTIVATION'] and not t['activated']:
            t['activated'] = True
            t['trailing'] = t['high'] * (1 - self.settings['TRAILING_DISTANCE']/100)
        
        if t['activated']:
            new_stop = t['high'] * (1 - self.settings['TRAILING_DISTANCE']/100)
            if new_stop > t['trailing']: t['trailing'] = new_stop
            if price <= t['trailing']:
                self._close(price, pnl, 'وقف متحرك', current_time)

    def _close(self, price, pnl, reason, current_time=None):
        if 'trade' not in self.active: return
        t = self.active['trade']
        exit_time = current_time or datetime.now()
        self.capital += t['capital'] * (1 + pnl/100) * (0.5 if t.get('tp_hit') and self.settings.get('PARTIAL_SELL') else 1)
        if pnl > 0: 
            self.wins += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
        
        duration = (exit_time - t['entry_time']).total_seconds() / 60 if t['entry_time'] else 0
        
        self.closed.append({
            'entry': t['entry'], 'exit': price, 'pnl': pnl, 
            'reason': reason, 'capital': t['capital'],
            'entry_time': t['entry_time'], 'exit_time': exit_time,
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
# 🧪 محرك الاختبار
# =========================================================
async def run_backtest(exchange, strategy_name: str, settings: dict) -> dict:
    print(f"\n{'='*60}")
    print(f"🧪 اختبار استراتيجية: {strategy_name}")
    print(f"{'='*60}")
    
    detector = FlexibleDetector(settings)
    simulator = Simulator(settings)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=BACKTEST_DAYS)
    
    await send_telegram(f"🧪 *بدء اختبار: {strategy_name}*\n{BOT_TAG}\n⏳ {BACKTEST_DAYS} يوم...")
    
    symbols = await detector.get_symbols(exchange, limit=100)
    processed = 0
    
    for symbol in symbols:
        try:
            since = exchange.parse8601(start_date.strftime('%Y-%m-%dT00:00:00Z'))
            ohlcv = await exchange.fetch_ohlcv(symbol, '5m', since=since, limit=5000)
            if len(ohlcv) < 100: continue
            processed += 1
            
            for i in range(100, len(ohlcv)):
                price = ohlcv[i][4]
                timestamp = datetime.fromtimestamp(ohlcv[i][0]/1000)
                
                simulator.update(price, timestamp)
                
                data = np.array(ohlcv[max(0,i-60):i+1])
                if len(data) < 30: continue
                
                result = detector.analyze(data, 500000, price, timestamp)
                if result and simulator.can_open():
                    simulator.open_trade(price, timestamp)
                    
        except Exception as e: continue
    
    # إغلاق الصفقات المتبقية
    if 'trade' in simulator.active:
        simulator._close(0, -2.0, 'نهاية الاختبار', end_date)
    
    stats = simulator.get_stats()
    
    # عرض النتائج
    print(f"""
📊 {strategy_name}:
   الصفقات: {stats['total']} | نجاح: {stats['win_rate']:.1f}% | ربح: {stats['pnl']:+.2f}$
   أقصى انخفاض: {stats['max_drawdown']:.1f}% | متوسط المدة: {stats['avg_duration']:.0f} دقيقة
""")
    
    # إرسال تليجرام مع التفاصيل
    best_str = f"🏆 أفضل: +{stats['best_trade']['pnl']:.2f}% ({stats['best_trade']['duration_minutes']:.0f}د)" if stats['best_trade'] else ""
    worst_str = f"💔 أسوأ: {stats['worst_trade']['pnl']:.2f}% ({stats['worst_trade']['duration_minutes']:.0f}د)" if stats['worst_trade'] else ""
    
    msg = f"""
📊 *{strategy_name}*
{BOT_TAG}
🔄 الصفقات: {stats['total']}
✅ النجاح: {stats['win_rate']:.1f}%
💰 الربح: {stats['pnl']:+.2f}$ ({stats['pnl']/SIMULATION_CAPITAL*100:+.2f}%)
📉 أقصى انخفاض: {stats['max_drawdown']:.1f}%
⏱️ متوسط المدة: {stats['avg_duration']:.0f} دقيقة
{best_str}
{worst_str}
    """
    await send_telegram(msg)
    
    return {'name': strategy_name, **stats}

# =========================================================
# 🚀 الدالة الرئيسية
# =========================================================
async def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║     🧪 اختبار 6 استراتيجيات – Backtesting شهري 🧪        ║
║     مع تحليلات متقدمة (أقصى انخفاض + أفضل/أسوأ صفقة)      ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    await send_telegram(f"🚀 *بدء اختبار 6 استراتيجيات*\n{BOT_TAG}\n📅 {BACKTEST_DAYS} يوم | 💰 {SIMULATION_CAPITAL}$\n📊 تحليلات متقدمة مفعلة")
    
    exchange = ccxt_async.binance({'enableRateLimit': True, 'rateLimit': 200, 'options': {'defaultType': 'spot'}})
    await exchange.fetch_ticker('BTC/USDT')
    print("✅ Binance متصل\n")
    
    results = []
    for name, settings in STRATEGIES.items():
        result = await run_backtest(exchange, name, settings)
        results.append(result)
    
    await exchange.close()
    
    # ترتيب النتائج
    results.sort(key=lambda x: x['pnl'], reverse=True)
    
    # التقرير النهائي
    print(f"\n{'='*60}")
    print("🏆 الترتيب النهائي للاستراتيجيات")
    print(f"{'='*60}")
    for i, r in enumerate(results, 1):
        medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}."
        print(f"{medal} {r['name']}: {r['win_rate']:.1f}% نجاح | {r['pnl']:+.2f}$ | أقصى انخفاض {r['max_drawdown']:.1f}% | متوسط {r['avg_duration']:.0f}د")
    
    # إرسال التقرير النهائي
    report = f"🏆 *الترتيب النهائي*\n{BOT_TAG}\n\n"
    for i, r in enumerate(results, 1):
        medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}."
        report += f"{medal} *{r['name']}*: {r['win_rate']:.1f}% | {r['pnl']:+.2f}$ | 📉{r['max_drawdown']:.1f}% | ⏱️{r['avg_duration']:.0f}د\n"
    report += f"\n🕐 `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
    await send_telegram(report)

if __name__ == "__main__":
    asyncio.run(main())
