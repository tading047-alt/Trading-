import ccxt
import pandas as pd
import backtrader as bt
import asyncio
from telegram import Bot
from datetime import datetime, timedelta

# --- الإعدادات ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class QuantInstitutionalStrategy(bt.Strategy):
    params = (
        ('atr_period', 14),
        ('atr_multiplier', 2.0), # الوقف يبتعد بمقدار 2 ATR
        ('min_score', 70),
    )

    def __init__(self):
        # 1. فلاتر الاتجاه والزخم
        self.ema9 = bt.indicators.EMA(period=9)
        self.ema21 = bt.indicators.EMA(period=21)
        self.ema50 = bt.indicators.EMA(period=50)
        self.ema200 = bt.indicators.EMA(period=200)
        self.adx = bt.indicators.ADX(period=14)
        self.rsi = bt.indicators.RSI(period=14)
        
        # 2. فلاتر السيولة والتذبذب
        self.bb = bt.indicators.BollingerBands(period=20)
        self.atr = bt.indicators.ATR(period=self.p.atr_period)
        self.vol_sma = bt.indicators.SMA(self.data.volume, period=20)

        # متغيرات التتبع
        self.entry_price = None
        self.max_price = 0
        self.trade_results = {
            'score': 0, 'details': "", 'status': "No Trade",
            'profit_pct': 0, 'whale_accumulation': "No"
        }

    def calculate_quant_score(self):
        score = 0
        reasons = []

        # أ- فلتر الاتجاه الصاعد (30 نقطة)
        if self.ema9[0] > self.ema21[0] > self.ema50[0] > self.ema200[0]:
            score += 30; reasons.append("Trend_Stacked")

        # ب- قوة الاتجاه ADX (15 نقطة)
        if self.adx[0] > 25:
            score += 15; reasons.append("Strong_Trend_ADX")

        # ج- انخناق البولنجر (15 نقطة)
        if (self.bb.top[0] - self.bb.bot[0]) < (self.atr[0] * 2):
            score += 15; reasons.append("Squeeze")

        # د- فوليوم الحيتان (20 نقطة)
        if self.data.volume[0] > self.vol_sma[0] * 2.5:
            score += 20; reasons.append("Whale_Volume")

        # هـ- فلتر الوقت (Session Filter) (10 نقاط)
        current_hour = bt.num2date(self.data.datetime[0]).hour
        if 8 <= current_hour <= 18: # ساعات لندن ونيويورك
            score += 10; reasons.append("Prime_Session")

        # و- دايفرجنس RSI بسيط (10 نقاط)
        if self.rsi[0] > self.rsi[-1] and self.rsi[0] > 50:
            score += 10; reasons.append("RSI_Momentum")

        return score, "|".join(reasons)

    def next(self):
        if not self.position:
            s, d = self.calculate_quant_score()
            if s >= self.p.min_score:
                self.buy()
                self.entry_price = self.data.close[0]
                self.max_price = self.data.close[0]
                self.trade_results.update({'score': s, 'details': d, 'entry_price': self.entry_price})
        else:
            # تحديث أعلى سعر
            self.max_price = max(self.max_price, self.data.high[0])
            
            # حساب الوقف المتحرك الذكي بناءً على ATR
            # الوقف ينزل بمقدار 2 * ATR عن أعلى سعر وصل له السعر
            trailing_stop = self.max_price - (self.atr[0] * self.p.atr_multiplier)
            
            # ضمان أن الوقف لا ينزل أبداً عن مستواه السابق (Trailing)
            if self.data.low[0] <= trailing_stop:
                self.close()
                profit = (self.data.close[0] - self.entry_price) / self.entry_price
                self.trade_results['status'] = "Win" if profit > 0 else "Loss"
                self.trade_results['profit_pct'] = round(profit * 100, 2)

class FullQuantScanner:
    def __init__(self):
        self.exchange = ccxt.binance()

    def check_relative_strength(self, symbol, btc_change):
        """مقارنة أداء العملة مقابل البيتكوين"""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            coin_change = ticker['percentage']
            return "Stronger" if coin_change > btc_change else "Weaker"
        except: return "Neutral"

    def run_backtest(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=500)
            df = pd.DataFrame(ohlcv, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['datetime'], unit='ms')
            
            cerebro = bt.Cerebro()
            cerebro.addstrategy(QuantInstitutionalStrategy)
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
    await bot.send_message(chat_id=CHAT_ID, text="🤖 بدأ الرادار الكمي المطور (ATR + BTC Strength + Session Filter)...")
    
    scanner = FullQuantScanner()
    
    # حساب أداء البيتكوين للمقارنة
    btc_ticker = scanner.exchange.fetch_ticker('BTC/USDT')
    btc_change = btc_ticker['percentage']
    
    tickers = scanner.exchange.fetch_tickers()
    symbols = [s[0] for s in sorted(tickers.items(), key=lambda x: x[1].get('quoteVolume', 0), reverse=True) if '/USDT' in s[0]][:300]
    
    final_data = []
    for i, sym in enumerate(symbols):
        print(f"[{i+1}/300] Quant Analysis: {sym}")
        res = scanner.run_backtest(sym)
        if res and res['score'] > 0:
            res['BTC_Rel_Strength'] = scanner.check_relative_strength(sym, btc_change)
            final_data.append(res)
    
    df = pd.DataFrame(final_data).sort_values(by='score', ascending=False)
    file_name = "Ultimate_Quant_Report.csv"
    df.to_csv(file_name, index=False)
    
    win_rate = len(df[df['status'] == "Win"]) / len(df[df['status'] != "No Trade"]) * 100 if len(df[df['status'] != "No Trade"]) > 0 else 0
    
    msg = f"🌟 **التقرير الكمي النهائي**\n\n"
    msg += f"📈 Win Rate: {round(win_rate, 2)}%\n"
    msg += f"🐳 صفقات بفلتر الحيتان: {len(df[df['details'].str.contains('Whale', na=False)])}\n"
    msg += f"⚡ أفضل سكور: {df['score'].max()}"
    
    await bot.send_message(chat_id=CHAT_ID, text=msg)
    with open(file_name, 'rb') as f:
        await bot.send_document(chat_id=CHAT_ID, document=f, caption="نتائج الاستراتيجية المؤسسية المطورة 📄")

if __name__ == "__main__":
    asyncio.run(main())
