#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio, pandas as pd, numpy as np, httpx, os
from datetime import datetime, timedelta
import ccxt.async_support as ccxt_async

# =========================================================
# ⚙️ الإعدادات المخصصة (ضع بيانات التليجرام هنا)
# =========================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "5067771509")

SETTINGS = {
    'INITIAL_CAPITAL': 1000.0,
    'MAX_CONCURRENT_TRADES': 10,
    'TAKE_PROFIT_START': 2.0,      # يبدأ التتبع من ربح 2%
    'TRAILING_DISTANCE': 1.0,      # المسافة من القمة 1%
    'STOP_LOSS': -2.0,             # وقف الخسارة ثابت -2%
    'FEE_RATE': 0.001,             # رسوم 0.1%
    'BACKTEST_DAYS': 30,
    'MIN_CONFIDENCE': 65
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
    except: pass

# =========================================================
# 🧠 المحاكي المتطور (Simulator)
# =========================================================
class Simulator:
    def __init__(self):
        self.capital = SETTINGS['INITIAL_CAPITAL']
        self.active_trades = []
        self.trades_history = []
        self.peak_balance = SETTINGS['INITIAL_CAPITAL']
        self.max_drawdown = 0.0

    def open_trade(self, price, symbol, timestamp):
        if len(self.active_trades) >= SETTINGS['MAX_CONCURRENT_TRADES']: return
        
        # حساب حجم الصفقة (الرصيد الحالي / 10) - دعم الربح المركب
        current_total_value = self.capital + sum(t['size'] for t in self.active_trades)
        slot_size = current_total_value / SETTINGS['MAX_CONCURRENT_TRADES']
        
        size = min(self.capital, slot_size)
        if size < 10: return
        
        fee = size * SETTINGS['FEE_RATE']
        self.capital -= (size + fee)
        
        self.active_trades.append({
            'symbol': symbol, 'entry': price, 'size': size,
            'high': price, 'entry_time': timestamp
        })

    def update(self, price, symbol, timestamp):
        for t in self.active_trades[:]:
            if t['symbol'] == symbol:
                if price > t['high']: t['high'] = price
                pnl_pct = (price - t['entry']) / t['entry'] * 100

                # تحديث أقصى نزول (Drawdown)
                current_total = self.capital + sum(tr['size'] for tr in self.active_trades)
                if current_total > self.peak_balance: self.peak_balance = current_total
                dd = (self.peak_balance - current_total) / self.peak_balance * 100
                if dd > self.max_drawdown: self.max_drawdown = dd

                # شروط الخروج
                if pnl_pct <= SETTINGS['STOP_LOSS']:
                    self._close(t, price, "🚫 وقف خسارة", timestamp)
                elif pnl_pct >= SETTINGS['TAKE_PROFIT_START']:
                    trailing_stop = t['high'] * (1 - SETTINGS['TRAILING_DISTANCE']/100)
                    if price <= trailing_stop:
                        self._close(t, price, "🔄 جني أرباح متحرك", timestamp)

    def _close(self, trade, price, reason, timestamp):
        pnl_raw = (price - trade['entry']) / trade['entry']
        exit_val = trade['size'] * (1 + pnl_raw)
        fee = exit_val * SETTINGS['FEE_RATE']
        final_amt = exit_val - fee
        self.capital += final_amt
        
        self.trades_history.append({
            'symbol': trade['symbol'], 'entry': trade['entry'], 'exit': price,
            'pnl': ((final_amt - trade['size']) / trade['size']) * 100,
            'reason': reason, 'entry_time': trade['entry_time'], 'exit_time': timestamp,
            'duration': (timestamp - trade['entry_time']).total_seconds() / 60
        })
        self.active_trades.remove(trade)

# =========================================================
# 🚀 الدالة الرئيسية
# =========================================================
async def main():
    print("⏳ بدء الاختبار العكسي المكثف...")
    exchange = ccxt_async.binance({'enableRateLimit': True})
    sim = Simulator()
    
    # فلتر البيتكوين البسيط
    btc_data = await exchange.fetch_ohlcv('BTC/USDT', '1h', limit=20)
    btc_trend = btc_data[-1][4] > np.mean([x[4] for x in btc_data])

    # جلب أفضل 50 عملة سيولة لتسريع الاختبار
    tickers = await exchange.fetch_tickers()
    symbols = [s for s, t in tickers.items() if s.endswith('/USDT') and (t.get('quoteVolume') or 0) > 200000][:50]

    start_date = datetime.now() - timedelta(days=SETTINGS['BACKTEST_DAYS'])
    since = exchange.parse8601(start_date.strftime('%Y-%m-%dT00:00:00Z'))

    for sym in symbols:
        try:
            ohlcv = await exchange.fetch_ohlcv(sym, '5m', since=since, limit=2000)
            data = np.array(ohlcv)
            for i in range(20, len(data)):
                price, ts = data[i][4], datetime.fromtimestamp(data[i][0]/1000)
                sim.update(price, sym, ts)
                
                # استراتيجية الدخول (تراكم سيولة + زخم)
                vol_spike = data[i][5] > np.mean(data[i-20:i, 5]) * 1.5
                if not any(t['symbol'] == sym for t in sim.active_trades) and btc_trend and vol_spike:
                    sim.open_trade(price, sym, ts)
        except: continue

    # --- معالجة التقارير ---
    h = sim.trades_history
    if not h: return print("❌ لا توجد صفقات منفذة.")
    
    h.sort(key=lambda x: x['pnl'], reverse=True)
    top_5, worst_5 = h[:5], h[-5:][::-1]
    
    final_pnl = ((sim.capital - SETTINGS['INITIAL_CAPITAL']) / SETTINGS['INITIAL_CAPITAL']) * 100
    win_rate = len([t for t in h if t['pnl'] > 0]) / len(h) * 100

    report = f"📊 *تقرير المحفظة الاستثماري*\n"
    report += f"💰 رأس المال النهائي: {sim.capital:.2f}$\n"
    report += f"📈 صافي الربح: {final_pnl:+.2f}%\n"
    report += f"📉 أقصى نزول (Drawdown): {sim.max_drawdown:.2f}%\n"
    report += f"✅ نسبة النجاح: {win_rate:.1f}%\n\n"

    async def format_trades(title, trade_list):
        msg = f"{title}\n"
        for i, t in enumerate(trade_list, 1):
            msg += f"*{i}. {t['symbol']}* | {t['pnl']:+.2f}%\n"
            msg += f"📅 {t['entry_time'].strftime('%m-%d %H:%M')} | 💵 {t['entry']:.4f} -> {t['exit']:.4f}\n"
        return msg + "\n"

    await send_telegram(report)
    await send_telegram(await format_trades("🏆 **أفضل 5 صفقات:**", top_5))
    await send_telegram(await format_trades("💔 **أسوأ 5 صفقات:**", worst_5))
    
    print("✅ تم إرسال التقارير لتليجرام.")
    await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
