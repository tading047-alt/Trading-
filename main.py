import ccxt
import pandas as pd
import backtrader as bt
import asyncio
import os
from telegram import Bot
from datetime import datetime, timedelta

# --- الإعدادات الخاصة بك ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class ProProScoringStrategy(bt.Strategy):
    params = (
        ('sma_long', 200),      # فلتر الاتجاه العام
        ('vol_factor', 2.0),    # فوليوم أكبر بمرتين من المتوسط
        ('trailing_perc', 0.02),# وقف متحرك 2%
        ('target_profit', 0.04),# هدف أولي 4% لرفع الوقف
    )

    def __init__(self):
        # 1. المؤشرات الفنية
        self.sma200 = bt.indicators.SMA(self.data.close, period=self.p.sma_long)
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20, devfactor=2)
        self.atr = bt.indicators.ATR(self.data, period=20)
        self.vol_avg = bt.indicators.SMA(self.data.volume, period=20)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        
        # 2. متغيرات تتبع الصفقة
        self.entry_price = None
        self.entry_date = None
        self.max_price = 0
        self.trade_status = "No_Trade"
        self.final_score = 0

    def calculate_score(self):
        score = 0
        # أ- فلتر الاتجاه: السعر فوق الـ 200 (قوي جداً)
        if self.data.close[0] > self.sma200[0]: score += 30
        # ب- انخناق البولنجر
        if (self.bb.top[0] - self.bb.bot[0]) < (self.atr[0] * 1.5): score += 20
        # ج- فوليوم انفجاري
        if self.data.volume[0] > self.vol_avg[0] * self.p.vol_factor: score += 20
        # د- قوة RSI (فوق الـ 50 يعني زخم صاعد)
        if self.rsi[0] > 50: score += 15
        # هـ- اختراق فعلي للبولنجر العلوي
        if self.data.close[0] > self.bb.top[0]: score += 15
        return score

    def next(self):
        if not self.position:
            current_score = self.calculate_score()
            # لا يدخل إلا إذا كان السكور قوي جداً (أكبر من 60)
            if current_score >= 60:
                self.buy()
                self.entry_price = self.data.close[0]
                self.max_price = self.data.close[0]
                self.final_score = current_score
                self.entry_date = bt.num2date(self.data.datetime[0])
                self.trade_status = "Open"
        else:
            # تحديث أقصى سعر وصل له البوت لتفعيل الوقف المتحرك
            self.max_price = max(self.max_price, self.data.high[0])
            
            # حساب الوقف المتحرك (Trailing Stop)
            # إذا نزل السعر 2% من أعلى قمة وصل لها بعد الدخول
            trailing_stop = self.max_price * (1.0 - self.p.trailing_perc)
            
            # شرط جني الأرباح (إذا حققنا 4% نرفع الوقف لنقطة الدخول فوراً)
            if self.data.close[0] >= self.entry_price * (1.0 + self.p.target_profit):
                trailing_stop = max(trailing_stop, self.entry_price * 1.01) # تأمين ربح 1%

            if self.data.low[0] <= trailing_stop:
                self.close()
                profit = (self.data.close[0] - self.entry_price) / self.entry_price
                self.trade_status = "Win" if profit > 0 else "Loss"

class CryptoScannerPro:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})

    def run_backtest(self, symbol):
        try:
            # نحتاج بيانات أكثر (500 شمعة) لحساب SMA 200 بدقة
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=500)
            df = pd.DataFrame(ohlcv, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['datetime'], unit='ms')
            
            cerebro = bt.Cerebro()
            cerebro.addstrategy(ProProScoringStrategy)
            data = bt.feeds.PandasData(dataname=df.set_index('datetime'))
            cerebro.adddata(data)
            cerebro.broker.setcash(1000.0)
            cerebro.broker.setcommission(commission=0.001)

            results = cerebro.run()
            strat = results[0]
            profit = round(((cerebro.broker.getvalue() - 1000) / 1000) * 100, 2)

            return {
                'Symbol': symbol,
                'Score': strat.final_score,
                'Date': strat.entry_date.strftime('%Y-%m-%d') if strat.entry_date else "N/A",
                'Status': strat.trade_status,
                'Final_Profit_%': profit
            }
        except: return None

async def main():
    scanner = CryptoScannerPro()
    tickers = scanner.exchange.fetch_tickers()
    symbols = [s[0] for s in sorted(tickers.items(), key=lambda x: x[1].get('quoteVolume', 0), reverse=True) if '/USDT' in s[0]][:300]
    
    print(f"🛠️ جاري تشغيل الاستراتيجية الاحترافية على 300 عملة...")
    all_results = []
    for i, sym in enumerate(symbols):
        print(f"[{i+1}/300] Analyzing {sym}...")
        res = scanner.run_backtest(sym)
        if res: all_results.append(res)
    
    df = pd.DataFrame(all_results).sort_values(by='Final_Profit_%', ascending=False)
    df.to_csv("Pro_Strategy_Report.csv", index=False)
    
    # رسالة تلغرام
    win_rate = len(df[df['Status'] == 'Win']) / len(df[df['Status'] != 'No_Trade']) * 100 if len(df[df['Status'] != 'No_Trade']) > 0 else 0
    msg = f"🏆 تقرير الاستراتيجية المدمجة (Scoring + Trailing)\n\n"
    msg += f"🔥 معدل الفوز (Win Rate): {round(win_rate, 2)}%\n"
    msg += f"📊 صفقات رابحة: {len(df[df['Status'] == 'Win'])}\n"
    msg += f"📉 صفقات خاسرة: {len(df[df['Status'] == 'Loss'])}\n"

    bot = Bot(token=TELEGRAM_TOKEN)
    async with bot:
        await bot.send_message(chat_id=CHAT_ID, text=msg)
        with open("Pro_Strategy_Report.csv", 'rb') as f:
            await bot.send_document(chat_id=CHAT_ID, document=f, caption="النتائج الكاملة بنظام السكور والوقف المتحرك 📄")

if __name__ == "__main__":
    asyncio.run(main())
