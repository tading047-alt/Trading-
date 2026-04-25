#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio, pandas as pd, numpy as np, httpx, os
from datetime import datetime, timedelta
import ccxt.async_support as ccxt_async

# =========================================================
# ⚙️ الإعدادات (تأكد من وضع بياناتك هنا)
# =========================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "5067771509")

SETTINGS = {
    'MIN_CONFIDENCE': 65,
    'MIN_VOLUME_24H': 150000,
    'MAX_SPREAD': 0.3,
    'TAKE_PROFIT': 3.5,
    'STOP_LOSS': -1.5,
    'TRAILING_ACTIVATION': 1.5,
    'TRAILING_DISTANCE': 0.5,
    'FEE_RATE': 0.001,           # 0.1% رسوم المنصة
    'INITIAL_CAPITAL': 500.0,
    'BACKTEST_DAYS': 30
}

# =========================================================
# 📨 دالة تليجرام
# =========================================================
async def send_telegram(text: str):
    if not TELEGRAM_TOKEN or "YOUR" in TELEGRAM_TOKEN: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text.strip(), "parse_mode": "Markdown"})
    except Exception as e:
        print(f"❌ Telegram Error: {e}")

# =========================================================
# 🧠 كاشف الإشارات والمؤشرات
# =========================================================
class Detector:
    def __init__(self):
        self.weights = {'calm': 45, 'whale': 55, 'boll': 40}

    async def check_market_trend(self, exchange):
        """ فلتر البيتكوين: يمنع الشراء إذا كان السوق هابطاً """
        try:
            btc = await exchange.fetch_ohlcv('BTC/USDT', '1h', limit=50)
            closes = np.array([c[4] for c in btc])
            ema = pd.Series(closes).ewm(span=20).mean().iloc[-1]
            return closes[-1] > ema
        except: return True

    async def get_symbols(self, exchange):
        tickers = await exchange.fetch_tickers()
        active = []
        for sym, t in tickers.items():
            if not sym.endswith('/USDT'): continue
            vol = t.get('quoteVolume') or 0
            if vol < SETTINGS['MIN_VOLUME_24H']: continue
            active.append(sym)
        return active[:100] # فحص أفضل 100 عملة سيولة

    def analyze(self, ohlcv: np.ndarray) -> bool:
        if len(ohlcv) < 30: return False
        closes = ohlcv[:, 4]; volumes = ohlcv[:, 5]
        
        # فلتر سريع: حجم التداول الأخير يجب أن يكون أعلى من المتوسط
        if volumes[-1] < np.mean(volumes[-20:]) * 1.2: return False
        
        # أنماط مبسطة (الهدوء، الحيتان، البولنجر)
        conf = 0
        # 1. Whale Pattern
        if volumes[-1] > np.mean(volumes[-10:]) * 1.5 and (np.max(closes[-5:]) - np.min(closes[-5:])) / closes[-1] < 0.015:
            conf += self.weights['whale']
        # 2. Bollinger Squeeze
        std = np.std(closes[-20:])
        if (std * 4 / np.mean(closes[-20:])) < 0.05:
            conf += self.weights['boll']
            
        return conf >= SETTINGS['MIN_CONFIDENCE']

# =========================================================
# 💰 المحاكي (Simulator)
# =========================================================
class Simulator:
    def __init__(self):
        self.capital = SETTINGS['INITIAL_CAPITAL']
        self.trades = []
        self.current_trade = None

    def open(self, price, symbol, timestamp):
        if self.current_trade: return
        size = min(self.capital * 0.2, 100) # دخول بـ 20% من المحفظة
        fee = size * SETTINGS['FEE_RATE']
        self.capital -= (size + fee)
        self.current_trade = {
            'symbol': symbol, 'entry': price, 'size': size,
            'high': price, 'entry_time': timestamp, 'activated': False
        }

    def update(self, price, timestamp):
        if not self.current_trade: return
        t = self.current_trade
        if price > t['high']: t['high'] = price
        pnl_pct = (price - t['entry']) / t['entry'] * 100

        # جني الأرباح / وقف الخسارة
        if pnl_pct >= SETTINGS['TAKE_PROFIT']:
            self._close(price, "🎯 هدف كامل", timestamp)
        elif pnl_pct <= SETTINGS['STOP_LOSS']:
            self._close(price, "🚫 وقف خسارة", timestamp)
        elif pnl_pct >= SETTINGS['TRAILING_ACTIVATION']:
            t['activated'] = True
            t_stop = t['high'] * (1 - SETTINGS['TRAILING_DISTANCE']/100)
            if price <= t_stop:
                self._close(price, "🔄 وقف متحرك", timestamp)

    def _close(self, price, reason, timestamp):
        t = self.current_trade
        pnl_raw = (price - t['entry']) / t['entry']
        exit_val = t['size'] * (1 + pnl_raw)
        fee = exit_val * SETTINGS['FEE_RATE']
        final_return = exit_val - fee
        self.capital += final_return
        
        self.trades.append({
            'symbol': t['symbol'], 'entry': t['entry'], 'exit': price,
            'pnl': ((final_return - t['size']) / t['size']) * 100,
            'reason': reason, 'duration': (timestamp - t['entry_time']).total_seconds() / 60
        })
        self.current_trade = None

# =========================================================
# 🚀 الدالة الرئيسية
# =========================================================
async def main():
    print("🚀 بدء الاختبار العكسي المحسن...")
    exchange = ccxt_async.binance({'enableRateLimit': True})
    detector = Detector()
    simulator = Simulator()
    
    is_bullish = await detector.check_market_trend(exchange)
    symbols = await detector.get_symbols(exchange)
    
    start_date = datetime.now() - timedelta(days=SETTINGS['BACKTEST_DAYS'])
    since = exchange.parse8601(start_date.strftime('%Y-%m-%dT00:00:00Z'))

    for sym in symbols:
        try:
            ohlcv = await exchange.fetch_ohlcv(sym, '5m', since=since, limit=1000)
            data = np.array(ohlcv)
            for i in range(30, len(data)):
                price = data[i][4]
                ts = datetime.fromtimestamp(data[i][0]/1000)
                simulator.update(price, ts)
                if not simulator.current_trade and is_bullish:
                    if detector.analyze(data[i-30:i+1]):
                        simulator.open(price, sym, ts)
        except: continue

    # --- تحليل النتائج وإرسال تليجرام ---
    trades = simulator.trades
    if not trades: 
        print("❌ لم يتم العثور على صفقات.")
        await exchange.close(); return

    trades.sort(key=lambda x: x['pnl'], reverse=True)
    top_5 = trades[:5]
    worst_5 = trades[-5:][::-1]
    
    win_rate = len([t for t in trades if t['pnl'] > 0]) / len(trades) * 100
    total_pnl = ((simulator.capital - SETTINGS['INITIAL_CAPITAL']) / SETTINGS['INITIAL_CAPITAL']) * 100

    report = f"📊 *تقرير Backtesting ({SETTINGS['BACKTEST_DAYS']} يوم)*\n\n"
    report += f"💰 صافي الربح: {total_pnl:+.2f}%\n"
    report += f"✅ نسبة النجاح: {win_rate:.1f}%\n"
    report += f"🔄 عدد الصفقات: {len(trades)}\n\n"
    
    report += "🏆 *أفضل 5 صفقات:*\n"
    for t in top_5:
        report += f"• {t['symbol']}: +{t['pnl']:.1f}% ({t['duration']:.0f}د)\n"
    
    report += "\n💔 *أسوأ 5 صفقات:*\n"
    for t in worst_5:
        report += f"• {t['symbol']}: {t['pnl']:.1f}% ({t['duration']:.0f}د)\n"

    await send_telegram(report)
    print("✅ تم إرسال التقرير بنجاح.")
    await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
