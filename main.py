import ccxt
import pandas as pd
import backtrader as bt
import asyncio
from telegram import Bot
from datetime import datetime, timedelta

# --- بياناتك الخاصة التي زودتني بها ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

# --- استراتيجية اصطياد الانفجارات (Squeeze Breakout) ---
class SqueezeStrategy(bt.Strategy):
    def __init__(self):
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20, devfactor=2)
        self.keltner_atr = bt.indicators.ATR(self.data, period=20)
        self.sma = bt.indicators.SMA(self.data.close, period=20)
        
        # متغيرات لتخزين بيانات أول نقطة دخول يتم رصدها
        self.entry_date = None
        self.entry_price = None

    def notify_order(self, order):
        if order.status in [order.Completed] and order.isbuy():
            if self.entry_date is None:  # تسجيل أول دخول فقط للتقرير
                self.entry_date = bt.num2date(order.executed.dt)
                self.entry_price = order.executed.price

    def next(self):
        bb_width = self.bb.top[0] - self.bb.bot[0]
        # حالة الضغط (Squeeze) هي وقود الانفجار القادم
        is_squeezing = bb_width < (self.keltner_atr[0] * 1.5)

        if not self.position:
            # شرط الدخول: ضغط + اختراق الحد العلوي لبولينجر
            if is_squeezing and self.data.close[0] > self.bb.top[0]:
                self.buy()
        elif self.data.close[0] < self.sma[0]:
            # الخروج عند العودة للمتوسط المتحرك (تأمين الربح)
            self.close()

# --- محرك البحث والاختبار (Backtesting Engine) ---
class CryptoScanner:
    def __init__(self):
        self.exchange = ccxt.binance()

    def run_backtest(self, symbol):
        try:
            # جلب بيانات آخر 30 يوم بفريم ساعة واحدة
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
            cerebro.broker.setcommission(commission=0.001) # رسوم بايننس 0.1%

            results = cerebro.run()
            strat = results[0]
            
            final_val = cerebro.broker.getvalue()
            profit_pct = round(((final_val - 1000.0) / 1000.0) * 100, 2)
            
            return {
                'Symbol': symbol,
                'Date_Entree': strat.entry_date.strftime('%Y-%m-%d') if strat.entry_date else "N/A",
                'Heure_Entree': strat.entry_date.strftime('%H:%M') if strat.entry_date else "N/A",
                'Prix_Entree': round(strat.entry_price, 6) if strat.entry_price else 0,
                'Resultat_Net_%': profit_pct
            }
        except:
            return None

async def send_to_telegram(full_data_list):
    if not full_data_list:
        print("❌ لم يتم العثور على أي صفقات في الاختبار.")
        return

    bot = Bot(token=TELEGRAM_TOKEN)
    df = pd.DataFrame(full_data_list).sort_values(by='Resultat_Net_%', ascending=False)
    
    file_path = "Detailed_Snowball_Report.csv"
    df.to_csv(file_path, index=False)

    summary = "🔥 تقرير صيد الانفجارات (آخر 30 يوم)\n"
    summary += f"📊 تم فحص 300 عملة\n\n"
    summary += "🚀 الأفضل أداءً:\n"
    for _, row in df.head(5).iterrows():
        summary += f"• {row['Symbol']}: {row['Resultat_Net_%']}% (دخل بسعر: {row['Prix_Entree']})\n"

    async with bot:
        await bot.send_message(chat_id=CHAT_ID, text=summary)
        with open(file_path, 'rb') as f:
            await bot.send_document(chat_id=CHAT_ID, document=f, caption="تقرير الأسعار والنتائج المفصلة 📄")
    print("✅ تم الإرسال إلى تلغرام!")

async def main():
    scanner = CryptoScanner()
    print("🚀 بدء فحص السوق (300 عملة)...")
    
    # جلب أفضل 300 عملة حسب حجم التداول
    tickers = scanner.exchange.fetch_tickers()
    symbols = [s[0] for s in sorted(tickers.items(), key=lambda x: x[1].get('quoteVolume', 0), reverse=True) if '/USDT' in s[0]][:300]
    
    all_results = []
    for i, symbol in enumerate(symbols):
        print(f"[{i+1}/300] فحص {symbol}...")
        res = scanner.run_backtest(symbol)
        if res:
            all_results.append(res)
    
    await send_to_telegram(all_results)

if __name__ == "__main__":
    asyncio.run(main())
