import ccxt
import pandas as pd
import backtrader as bt
import asyncio
import os
from telegram import Bot
from datetime import datetime, timedelta

# --- إعدادات التلغرام ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

# --- استراتيجية السكور المتقدمة (بدون مكتبات خارجية) ---
class SmartScoringStrategy(bt.Strategy):
    params = (
        ('sl', 0.02),    # وقف خسارة 2%
        ('tp', 0.04),    # جني أرباح 4%
        ('min_score', 30), 
    )

    def __init__(self):
        # مؤشرات Backtrader الأصلية (أكثر استقراراً)
        self.sma50 = bt.indicators.SimpleMovingAverage(self.data.close, period=50)
        self.sma200 = bt.indicators.SimpleMovingAverage(self.data.close, period=200)
        self.rsi = bt.indicators.RelativeStrengthIndex(self.data.close, period=14)
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20, devfactor=2)
        self.atr = bt.indicators.AverageTrueRange(self.data, period=20)
        self.vol_sma = bt.indicators.SimpleMovingAverage(self.data.volume, period=20)

        self.trade_log = {
            'entry_date': "N/A", 'entry_hour': "N/A",
            'entry_price': 0, 'exit_price': 0,
            'score': 0, 'status': "No Trade"
        }

    def get_score(self):
        score = 0
        # 1. انخناق البولنجر (Squeeze)
        if (self.bb.top[0] - self.bb.bot[0]) < (self.atr[0] * 1.5): score += 10
        # 2. التقاطع الذهبي
        if self.sma50[0] > self.sma200[0]: score += 10
        # 3. دايفرجنس RSI (تبسيط: RSI صاعد والسعر في قاع)
        if self.rsi[0] < 40 and self.rsi[0] > self.rsi[-1]: score += 10
        # 4. اختراق السعر للبولنجر العلوي
        if self.data.close[0] > self.bb.top[0]: score += 10
        # 5. سيولة ضخمة (Volume Spike)
        if self.data.volume[0] > self.vol_sma[0] * 1.5: score += 10
        return score

    def next(self):
        if not self.position:
            s = self.get_score()
            if s >= self.p.min_score:
                self.trade_log['score'] = s
                self.trade_log['entry_price'] = self.data.close[0]
                self.trade_log['entry_date'] = bt.num2date(self.data.datetime[0]).strftime('%Y-%m-%d')
                self.trade_log['entry_hour'] = bt.num2date(self.data.datetime[0]).strftime('%H:%M')
                
                self.buy()
                self.sl_price = self.data.close[0] * (1.0 - self.p.sl)
                self.tp_price = self.data.close[0] * (1.0 + self.p.tp)
        else:
            # مراقبة الأهداف
            if self.data.low[0] <= self.sl_price:
                self.trade_log['status'] = "Loss (-2%)"
                self.trade_log['exit_price'] = self.sl_price
                self.close()
            elif self.data.high[0] >= self.tp_price:
                self.trade_log['status'] = "Win (+4%)"
                self.trade_log['exit_price'] = self.tp_price
                self.close()

# --- مدير الباكتيست ---
class BacktestManager:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})

    def run(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=400)
            df = pd.DataFrame(ohlcv, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['datetime'], unit='ms')
            
            cerebro = bt.Cerebro()
            cerebro.addstrategy(SmartScoringStrategy)
            data = bt.feeds.PandasData(dataname=df.set_index('datetime'))
            cerebro.adddata(data)
            cerebro.broker.setcash(1000.0)
            
            results = cerebro.run()
            res = results[0].trade_log
            res['Symbol'] = symbol
            res['Final_Balance'] = round(cerebro.broker.getvalue(), 2)
            return res
        except:
            return None

async def main():
    manager = BacktestManager()
    tickers = manager.exchange.fetch_tickers()
    symbols = [s[0] for s in sorted(tickers.items(), key=lambda x: x[1].get('quoteVolume', 0), reverse=True) if '/USDT' in s[0]][:300]
    
    print(f"📡 بدء التحليل المتقدم لـ 300 عملة...")
    final_data = []
    for i, sym in enumerate(symbols):
        print(f"[{i+1}/300] Analyzing {sym}...")
        report = manager.run(sym)
        if report: final_data.append(report)
    
    # تصدير للـ CSV
    df = pd.DataFrame(final_data)
    file_path = "Scoring_Report_No_TA.csv"
    df.to_csv(file_path, index=False)
    
    # إرسال تلغرام
    bot = Bot(token=TELEGRAM_TOKEN)
    wins = len(df[df['status'] == "Win (+4%)"])
    losses = len(df[df['status'] == "Loss (-2%)"])
    
    msg = f"📊 تقرير السكور الذكي (بدون pandas_ta)\n\n"
    msg += f"✅ صفقات ناجحة: {wins}\n"
    msg += f"❌ صفقات خاسرة: {losses}\n"
    msg += f"📈 معدل الربح: {round(wins/(wins+losses)*100, 1) if (wins+losses)>0 else 0}%"

    async with bot:
        await bot.send_message(chat_id=CHAT_ID, text=msg)
        with open(file_path, 'rb') as f:
            await bot.send_document(chat_id=CHAT_ID, document=f, caption="النتائج الكاملة والسكور 📄")

if __name__ == "__main__":
    asyncio.run(main())
