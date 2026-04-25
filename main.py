import ccxt
import pandas as pd
import backtrader as bt
import asyncio
import os
from telegram import Bot
from datetime import datetime, timedelta

# --- إعدادات التلغرام (ضع بياناتك هنا) ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

# --- 1. تعريف استراتيجية الانفجار (Bollinger Squeeze) ---
class SqueezeStrategy(bt.Strategy):
    def __init__(self):
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20, devfactor=2)
        self.keltner_atr = bt.indicators.ATR(self.data, period=20)
        self.sma = bt.indicators.SMA(self.data.close, period=20)

    def next(self):
        # حساب عرض حدود بولينجر
        bb_width = self.bb.top[0] - self.bb.bot[0]
        # حالة الضغط (Squeeze)
        is_squeezing = bb_width < (self.keltner_atr[0] * 1.5)

        if not self.position:
            if is_squeezing and self.data.close[0] > self.bb.top[0]:
                self.buy()
        elif self.data.close[0] < self.sma[0]:
            self.close()

# --- 2. وظائف النظام ---
class SnowballScanner:
    def __init__(self):
        self.exchange = ccxt.binance()

    def get_symbols(self):
        print("🔍 جاري جلب أفضل 300 عملة من بايننس...")
        tickers = self.exchange.fetch_tickers()
        sorted_tickers = sorted(tickers.items(), key=lambda x: x[1].get('quoteVolume', 0), reverse=True)
        return [s[0] for s in sorted_tickers if '/USDT' in s[0]][:300]

    def run_backtest(self, symbol):
        try:
            # جلب بيانات شهر واحد (فريم ساعة)
            since = self.exchange.parse8601((datetime.now() - timedelta(days=30)).isoformat())
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', since=since)
            if len(ohlcv) < 100: return None

            df = pd.DataFrame(ohlcv, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['datetime'], unit='ms')
            df.set_index('datetime', inplace=True)

            cerebro = bt.Cerebro()
            cerebro.addstrategy(SqueezeStrategy)
            data = bt.feeds.PandasData(dataname=df)
            cerebro.adddata(data)
            cerebro.broker.setcash(1000.0)
            cerebro.broker.setcommission(commission=0.001) # رسوم 0.1%

            cerebro.run()
            final_val = cerebro.broker.getvalue()
            return round(((final_val - 1000.0) / 1000.0) * 100, 2)
        except Exception as e:
            return None

async def send_to_telegram(results):
    if not results:
        print("❌ لا توجد نتائج لإرسالها.")
        return

    bot = Bot(token=TELEGRAM_TOKEN)
    
    # تحويل للـ CSV
    df = pd.DataFrame(list(results.items()), columns=['Symbol', 'Profit_%']).sort_values(by='Profit_%', ascending=False)
    file_path = "scan_results.csv"
    df.to_csv(file_path, index=False)

    # ملخص أفضل 5
    summary = "🚀 تقرير انفجار العملات (30 يوم)\n\n"
    summary += "🔝 الأفضل أداءً:\n"
    for _, row in df.head(5).iterrows():
        summary += f"• {row['Symbol']}: {row['Profit_%']}%\n"

    async with bot:
        # إرسال الرسالة
        await bot.send_message(chat_id=CHAT_ID, text=summary)
        # إرسال الملف
        with open(file_path, 'rb') as f:
            await bot.send_document(chat_id=CHAT_ID, document=f, caption="التقرير الكامل لـ 300 عملة 📄")
    
    print("✅ تم إرسال التقرير لتلغرام بنجاح.")

# --- 3. التشغيل الرئيسي ---
async def main():
    scanner = SnowballScanner()
    symbols = scanner.get_symbols()
    
    all_results = {}
    for i, symbol in enumerate(symbols):
        print(f"[{i+1}/300] فحص {symbol}...")
        profit = scanner.run_backtest(symbol)
        if profit is not None:
            all_results[symbol] = profit
    
    await send_to_telegram(all_results)

if __name__ == "__main__":
    asyncio.run(main())
