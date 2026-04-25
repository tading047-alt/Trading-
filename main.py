#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio, pandas as pd, numpy as np, httpx, os
from datetime import datetime, timedelta
import ccxt.async_support as ccxt_async

# =========================================================
# ⚙️ الإعدادات المتقدمة
# =========================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")

SETTINGS = {
    'INITIAL_CAPITAL': 1000.0,
    'MAX_CONCURRENT_TRADES': 10,
    'TAKE_PROFIT_START': 2.0,      # التتبع يبدأ من 2%
    'TRAILING_DISTANCE': 1.0,      # فرق اللاحق 1%
    'STOP_LOSS': -2.0,             # وقف خسارة صارم
    'FEE_RATE': 0.001,             # رسوم المنصة
    'BACKTEST_DAYS': 30,
    'MIN_SCORE_REQUIRED': 75       # الحد الأدنى للسكور لدخول الصفقة
}

# =========================================================
# 🧠 محرك السكور وتحليل الفريمات (MTF Engine)
# =========================================================
class StrategyEngine:
    def __init__(self):
        self.weights = {
            'trend_1h': 30,        # توافق الاتجاه مع الساعة
            'rsi_div_15m': 20,     # دايفرجنس على الـ 15 دقيقة
            'vol_flow_15m': 20,    # تدفق السيولة
            'squeeze_5m': 15,      # انفجار البولنجر على الـ 5 دقائق
            'retest_5m': 15        # تأكيد إعادة الاختبار
        }

    def calculate_rsi(self, series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def analyze_mtf(self, data_1h, data_15m, data_5m):
        score = 0
        
        # 1. تحليل فريم الساعة (الاتجاه العام - EMA 200)
        c_1h = pd.Series([x[4] for x in data_1h])
        ema_200 = c_1h.ewm(span=200).mean().iloc[-1]
        if c_1h.iloc[-1] > ema_200:
            score += self.weights['trend_1h']

        # 2. تحليل فريم 15 دقيقة (الدايفرجنس والسيولة)
        c_15m = pd.Series([x[4] for x in data_15m])
        v_15m = pd.Series([x[5] for x in data_15m])
        rsi_15m = self.calculate_rsi(c_15m)
        
        # دايفرجنس بسيط: السعر يهبط والـ RSI يصعد
        if c_15m.iloc[-1] < c_15m.iloc[-5] and rsi_15m.iloc[-1] > rsi_15m.iloc[-5]:
            score += self.weights['rsi_div_15m']
        
        if v_15m.iloc[-1] > v_15m.rolling(20).mean().iloc[-1] * 1.5:
            score += self.weights['vol_flow_15m']

        # 3. تحليل فريم 5 دقائق (نقطة الدخول وإعادة الاختبار)
        c_5m = pd.Series([x[4] for x in data_5m])
        h_5m = pd.Series([x[2] for x in data_5m])
        
        # حساب الاختراق وإعادة الاختبار
        recent_high = h_5m.iloc[-20:-5].max()
        breakout = h_5m.iloc[-5:].max() > recent_high
        retest = c_5m.iloc[-1] <= recent_high * 1.005 and c_5m.iloc[-1] >= recent_high * 0.998
        
        if breakout and retest:
            score += self.weights['retest_5m']
            
        return score, (breakout and retest)

# =========================================================
# 💰 المحاكي (Simulator)
# =========================================================
class Simulator:
    def __init__(self):
        self.capital = SETTINGS['INITIAL_CAPITAL']
        self.active_trades = []
        self.history = []
        self.peak = SETTINGS['INITIAL_CAPITAL']
        self.max_dd = 0.0

    def open(self, price, symbol, timestamp):
        if len(self.active_trades) >= SETTINGS['MAX_CONCURRENT_TRADES']: return
        
        # إدارة رأس المال المركب
        total_val = self.capital + sum(t['size'] for t in self.active_trades)
        slot_size = total_val / SETTINGS['MAX_CONCURRENT_TRADES']
        size = min(self.capital, slot_size)
        
        if size < 10: return
        fee = size * SETTINGS['FEE_RATE']
        self.capital -= (size + fee)
        self.active_trades.append({'symbol': symbol, 'entry': price, 'size': size, 'high': price, 'time': timestamp})

    def update(self, price, symbol, timestamp):
        for t in self.active_trades[:]:
            if t['symbol'] == symbol:
                if price > t['high']: t['high'] = price
                pnl = (price - t['entry']) / t['entry'] * 100
                
                # حساب Drawdown
                curr_total = self.capital + sum(tr['size'] for tr in self.active_trades)
                if curr_total > self.peak: self.peak = curr_total
                dd = (self.peak - curr_total) / self.peak * 100
                if dd > self.max_dd: self.max_dd = dd

                # خروج
                if pnl <= SETTINGS['STOP_LOSS']:
                    self._close(t, price, "🚫 SL", timestamp)
                elif pnl >= SETTINGS['TAKE_PROFIT_START']:
                    t_stop = t['high'] * (1 - SETTINGS['TRAILING_DISTANCE']/100)
                    if price <= t_stop:
                        self._close(t, price, "🔄 Trailing", timestamp)

    def _close(self, t, price, reason, ts):
        pnl_raw = (price - t['entry']) / t['entry']
        val = t['size'] * (1 + pnl_raw)
        self.capital += (val - (val * SETTINGS['FEE_RATE']))
        self.history.append({
            'symbol': t['symbol'], 'pnl': ((val - t['size']) / t['size']) * 100,
            'entry': t['entry'], 'exit': price, 'time': t['time'], 'reason': reason
        })
        self.active_trades.remove(t)

# =========================================================
# 🚀 تشغيل البوت
# =========================================================
async def main():
    exchange = ccxt_async.binance({'enableRateLimit': True})
    engine = StrategyEngine()
    sim = Simulator()

    # جلب العملات القوية فقط
    tickers = await exchange.fetch_tickers()
    symbols = [s for s, t in tickers.items() if s.endswith('/USDT') and (t.get('quoteVolume', 0) > 500000)][:30]

    print(f"📊 جاري تحليل {len(symbols)} عملة عبر 3 فريمات زمنية...")

    for sym in symbols:
        try:
            # جلب بيانات MTF
            d1h = await exchange.fetch_ohlcv(sym, '1h', limit=200)
            d15m = await exchange.fetch_ohlcv(sym, '15m', limit=100)
            d5m = await exchange.fetch_ohlcv(sym, '5m', limit=100)
            
            # محاكاة زمنية بسيطة (آخر 50 شمعة من فريم 5 دقائق)
            for i in range(50, len(d5m)):
                price = d5m[i][4]
                ts = datetime.fromtimestamp(d5m[i][0]/1000)
                sim.update(price, sym, ts)
                
                # حساب السكور وتأكيد نقطة الدخول
                score, is_retest = engine.analyze_mtf(d1h, d15m, d5m[i-50:i+1])
                
                if score >= SETTINGS['MIN_SCORE_REQUIRED'] and is_retest:
                    if not any(t['symbol'] == sym for t in sim.active_trades):
                        sim.open(price, sym, ts)
        except: continue

    # إرسال التقارير
    h = sorted(sim.history, key=lambda x: x['pnl'], reverse=True)
    if h:
        report = f"✅ *إنتهاء الاختبار العكسي*\n💰 الرصيد: {sim.capital:.2f}$\n📉 Max DD: {sim.max_dd:.2f}%"
        best = f"🏆 *أفضل صفقة:*\n{h[0]['symbol']} | {h[0]['pnl']:+.2f}%\n📅 {h[0]['time'].strftime('%m-%d %H:%M')}"
        worst = f"💔 *أسوأ صفقة:*\n{h[-1]['symbol']} | {h[-1]['pnl']:+.2f}%\n📅 {h[-1]['time'].strftime('%m-%d %H:%M')}"
        
        print(report)
        # هنا يتم استدعاء send_telegram (تأكد من وضع التوكن)
    
    await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
