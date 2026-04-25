import ccxt
import pandas as pd
import backtrader as bt
import asyncio
from telegram import Bot
from datetime import datetime, timedelta

# --- الإعدادات ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class ProTrailingScoreStrategy(bt.Strategy):
    params = (
        ('trigger_profit', 0.03), # تفعيل الوقف عند ربح 3%
        ('trailing_dist', 0.02),  # الوقف يلحق السعر بفارق 2%
        ('initial_sl', 0.02),     # وقف خسارة مبدئي 2%
        ('min_score', 65),
    )

    def __init__(self):
        # المؤشرات المطلوبة
        self.ema9 = bt.indicators.EMA(period=9)
        self.ema21 = bt.indicators.EMA(period=21)
        self.ema50 = bt.indicators.EMA(period=50)
        self.ema200 = bt.indicators.EMA(period=200)
        self.rsi = bt.indicators.RSI(period=14)
        self.macd = bt.indicators.MACD()
        self.bb = bt.indicators.BollingerBands(period=20)
        self.atr = bt.indicators.ATR(period=20)
        self.vol_sma = bt.indicators.SMA(self.data.volume, period=20)

        # متغيرات التتبع
        self.entry_price = None
        self.max_price = 0
        self.trailing_active = False
        self.trade_results = {
            'score': 0, 'details': "", 'status': "No Trade",
            'entry_price': 0, 'exit_price': 0, 'profit_final': 0
        }

    def get_score(self):
        score = 0
        reasons = []
        if self.ema9[0] > self.ema21[0] > self.ema50[0] > self.ema200[0]:
            score += 30; reasons.append("EMAs_Trend")
        if (self.bb.top[0] - self.bb.bot[0]) < (self.atr[0] * 1.5):
            score += 20; reasons.append("Squeeze")
        if self.data.volume[0] > self.vol_sma[0] * 2.5:
            score += 20; reasons.append("Whale_Vol")
        if 50 < self.rsi[0] < 70:
            score += 15; reasons.append("RSI_Strong")
        if self.macd.macd[0] > self.macd.signal[0]:
            score += 15; reasons.append("MACD_Up")
        return score, "|".join(reasons)

    def next(self):
        if not self.position:
            s, d = self.get_score()
            if s >= self.p.min_score:
                self.buy()
                self.entry_price = self.data.close[0]
                self.max_price = self.data.close[0]
                self.trailing_active = False
                self.trade_results.update({'score': s, 'details': d, 'entry_price': self.entry_price})
        else:
            # تحديث أعلى سعر وصل له السعر بعد الدخول
            self.max_price = max(self.max_price, self.data.high[0])
            current_profit = (self.max_price - self.entry_price) / self.entry_price

            # تفعيل الوقف المتحرك عند ربح 3%
            if not self.trailing_active and current_profit >= self.p.trigger_profit:
                self.trailing_active = True

            # تحديد سعر الوقف
            if self.trailing_active:
                # الوقف يلحق السعر بفارق 2% من أعلى قمة
                exit_stop = self.max_price * (1 - self.p.trailing_dist)
            else:
                # وقف الخسارة المبدئي 2%
                exit_stop = self.entry_price * (1 - self.p.initial_sl)

            if self.data.low[0] <= exit_stop:
                self.close()
                self.trade_results['exit_price'] = exit_stop
                profit_pct = (exit_stop - self.entry_price) / self.entry_price
                self.trade_results['status'] = "Win" if profit_pct > 0 else "Loss"
                self.trade_results['profit_final'] = round(profit_pct * 100, 2)

class BacktestProcessor:
    def __init__(self):
        self.exchange = ccxt.binance()

    def run(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=500)
            df = pd.DataFrame(ohlcv, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['datetime'], unit='ms')
            cerebro = bt.Cerebro()
            cerebro.addstrategy(ProTrailingScoreStrategy)
            data = bt.feeds.PandasData(dataname=df.set_index('datetime'))
            cerebro.adddata(data)
            cerebro.broker.setcash(1000.0)
            results = cerebro.run()
            res = results[0].trade_results
            res['Symbol'] = symbol
            return res
        except: return None

async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text="🔍 جاري فحص 300 عملة بنظام Trailing SL والسكور...")
    
    proc = BacktestProcessor()
    tickers = proc.exchange.fetch_tickers()
    symbols = [s[0] for s in sorted(tickers.items(), key=lambda x: x[1].get('quoteVolume', 0), reverse=True) if '/USDT' in s[0]][:300]
    
    final_data = []
    for i, sym in enumerate(symbols):
        print(f"[{i+1}/300] Testing {sym}")
        res = proc.run(sym)
        if res: final_data.append(res)
    
    df = pd.DataFrame(final_data).sort_values(by='score', ascending=False)
    file_name = "Trailing_Score_Report.csv"
    df.to_csv(file_name, index=False)
    
    msg = f"🏁 اكتمل التحليل\n✅ صفقات رابحة (متحركة): {len(df[df['status'] == 'Win'])}\n❌ صفقات خاسرة: {len(df[df['status'] == 'Loss'])}\n⭐ أعلى سكور: {df['score'].max()}"
    await bot.send_message(chat_id=CHAT_ID, text=msg)
    with open(file_name, 'rb') as f:
        await bot.send_document(chat_id=CHAT_ID, document=f, caption="تقرير السكور والوقف المتحرك التفصيلي 📄")

if __name__ == "__main__":
    asyncio.run(main())
