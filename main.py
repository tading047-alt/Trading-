import ccxt
import pandas as pd
import pandas_ta as ta
import backtrader as bt
import asyncio
import os
from telegram import Bot
from datetime import datetime, timedelta

# --- إعدادات التلغرام الخاصة بك ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

# --- استراتيجية السكور المتقدمة ---
class ScoreBacktestStrategy(bt.Strategy):
    params = (('threshold', 30),) # الحد الأدنى للسكور لدخول الصفقة

    def __init__(self):
        # تعريف المؤشرات داخل Backtrader
        self.sma50 = bt.indicators.SimpleMovingAverage(self.data.close, period=50)
        self.sma200 = bt.indicators.SimpleMovingAverage(self.data.close, period=200)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20, devfactor=2)
        self.atr = bt.indicators.ATR(self.data, period=20)
        
        self.entry_date = None
        self.entry_price = None
        self.final_score = 0

    def calculate_score(self):
        score = 0
        # 1. انخناق بولنجر (10 نقاط)
        if (self.bb.top[0] - self.bb.bot[0]) < (self.atr[0] * 1.5):
            score += 10
        # 2. التقاطع الذهبي (10 نقاط)
        if self.sma50[0] > self.sma200[0]:
            score += 10
        # 3. RSI Divergence (تبسيط: RSI هابط والسعر صاعد أو العكس) (10 نقاط)
        if self.rsi[0] < 30: # ذروة بيع (قوة كامنة)
            score += 10
        # 4. حجم تداول انفجاري (10 نقاط)
        if self.data.volume[0] > bt.indicators.SMA(self.data.volume, period=20)[0] * 2:
            score += 10
        # 5. اتجاه السعر (10 نقاط)
        if self.data.close[0] > self.bb.top[0]:
            score += 10
            
        return score

    def next(self):
        current_score = self.calculate_score()
        
        if not self.position:
            # لا يدخل إلا إذا تجاوز السكور الحد المطلوب (مثلاً 30/50)
            if current_score >= self.p.threshold:
                self.buy()
                self.entry_date = bt.num2date(self.data.datetime[0])
                self.entry_price = self.data.close[0]
                self.final_score = current_score
        else:
            # خروج عند كسر المتوسط المتحرك أو ضعف السكور
            if self.data.close[0] < self.bb.mid[0]:
                self.close()

# --- محرك البحث والفحص ---
class HeavyScanner:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})

    def run_backtest(self, symbol):
        try:
            since = self.exchange.parse8601((datetime.now() - timedelta(days=30)).isoformat())
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', since=since)
            if len(ohlcv) < 200: return None

            df = pd.DataFrame(ohlcv, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['datetime'], unit='ms')
            
            data_feed = bt.feeds.PandasData(dataname=df.set_index('datetime'))
            cerebro = bt.Cerebro()
            cerebro.addstrategy(ScoreBacktestStrategy)
            cerebro.adddata(data_feed)
            cerebro.broker.setcash(1000.0)
            cerebro.broker.setcommission(commission=0.001)

            results = cerebro.run()
            strat = results[0]
            profit = round(((cerebro.broker.getvalue() - 1000) / 1000) * 100, 2)

            return {
                'Symbol': symbol,
                'Score_At_Entry': strat.final_score,
                'Date_Entree': strat.entry_date.strftime('%Y-%m-%d') if strat.entry_date else "No Trade",
                'Prix_Entree': round(strat.entry_price, 6) if strat.entry_price else 0,
                'Resultat_%': profit
            }
        except:
            return None

async def send_report(data):
    df = pd.DataFrame(data).sort_values(by='Resultat_%', ascending=False)
    file_path = "Scoring_Backtest_Final.csv"
    df.to_csv(file_path, index=False)

    report = "📈 نتائج باكتيست نظام السكور (300 عملة)\n\n"
    report += f"✅ تم العثور على صفقات لـ {len(df[df['Score_At_Entry'] > 0])} عملة.\n"
    report += f"🏆 أفضل نتيجة: {df['Resultat_%'].max()}%\n"

    bot = Bot(token=TELEGRAM_TOKEN)
    async with bot:
        await bot.send_message(chat_id=CHAT_ID, text=report)
        with open(file_path, 'rb') as f:
            await bot.send_document(chat_id=CHAT_ID, document=f, caption="تقرير السكور المفصل لجميع العملات 📄")

async def main():
    scanner = HeavyScanner()
    tickers = scanner.exchange.fetch_tickers()
    symbols = [s[0] for s in sorted(tickers.items(), key=lambda x: x[1].get('quoteVolume', 0), reverse=True) if '/USDT' in s[0]][:300]
    
    final_results = []
    for i, symbol in enumerate(symbols):
        print(f"[{i+1}/300] Testing {symbol} with Scoring System...")
        res = scanner.run_backtest(symbol)
        if res: final_results.append(res)
    
    await send_report(final_results)

if __name__ == "__main__":
    asyncio.run(main())
