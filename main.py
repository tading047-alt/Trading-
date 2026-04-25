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

# --- استراتيجية اصطياد الانفجارات (Bollinger Squeeze) ---
class SqueezeStrategy(bt.Strategy):
    def __init__(self):
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20, devfactor=2)
        self.keltner_atr = bt.indicators.ATR(self.data, period=20)
        self.sma = bt.indicators.SMA(self.data.close, period=20)
        
        # لتخزين بيانات الدخول
        self.entry_date = None
        self.entry_price = None

    def notify_order(self, order):
        # تسجيل أول صفقة شراء مكتملة فقط لأغراض التقرير
        if order.status in [order.Completed] and order.isbuy():
            if self.entry_date is None:
                self.entry_date = bt.num2date(order.executed.dt)
                self.entry_price = order.executed.price

    def next(self):
        bb_width = self.bb.top[0] - self.bb.bot[0]
        # حالة الضغط (Squeeze)
        is_squeezing = bb_width < (self.keltner_atr[0] * 1.5)

        if not self.position:
            # شرط الدخول: انفجار سعري بعد ضغط
            if is_squeezing and self.data.close[0] > self.bb.top[0]:
                self.buy()
        elif self.data.close[0] < self.sma[0]:
            # الخروج عند العودة للمتوسط المتحرك
            self.close()

# --- محرك الفحص والاختبار ---
class CryptoScanner:
    def __init__(self):
        self.exchange = ccxt.binance({
            'enableRateLimit': True
        })

    def get_top_300_symbols(self):
        print("🔍 جاري جلب أنشط 300 عملة من بايننس...")
        tickers = self.exchange.fetch_tickers()
        # الترتيب حسب حجم التداول (Volume)
        sorted_symbols = sorted(tickers.items(), key=lambda x: x[1].get('quoteVolume', 0), reverse=True)
        return [s[0] for s in sorted_symbols if '/USDT' in s[0]][:300]

    def run_backtest(self, symbol):
        try:
            # جلب بيانات آخر 30 يوم (فريم 1 ساعة)
            since = self.exchange.parse8601((datetime.now() - timedelta(days=30)).isoformat())
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', since=since)
            if len(ohlcv) < 50: return None

            df = pd.DataFrame(ohlcv, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['datetime'], unit='ms')
            df.set_index('datetime', inplace=True)

            cerebro = bt.Cerebro()
            cerebro.addstrategy(SqueezeStrategy)
            data = bt.feeds.PandasData(dataname=df)
            cerebro.adddata(data)
            cerebro.broker.setcash(1000.0)
            cerebro.broker.setcommission(commission=0.001) # رسوم 0.1%

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
        except Exception:
            return None

async def send_to_telegram(all_data):
    if not all_data:
        print("❌ لا توجد نتائج.")
        return

    # مسح الملف القديم لضمان تحديث البيانات
    file_path = "Backtest_Report.csv"
    if os.path.exists(file_path):
        os.remove(file_path)

    bot = Bot(token=TELEGRAM_TOKEN)
    df = pd.DataFrame(all_data).sort_values(by='Resultat_Net_%', ascending=False)
    df.to_csv(file_path, index=False)

    summary = "🚀 تقرير رادار الانفجارات (آخر 30 يوم)\n\n"
    summary += "🔝 أفضل 5 نتائج:\n"
    for _, row in df.head(5).iterrows():
        summary += f"• {row['Symbol']}: {row['Resultat_Net_%']}% (Prix: {row['Prix_Entree']})\n"

    async with bot:
        # إرسال الملخص
        await bot.send_message(chat_id=CHAT_ID, text=summary)
        # إرسال الملف التفصيلي الجديد
        with open(file_path, 'rb') as f:
            await bot.send_document(
                chat_id=CHAT_ID, 
                document=f, 
                caption=f"تقرير تفصيلي لـ {len(df)} عملة 📄\nبتاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
    print("✅ تم تحديث التقرير وإرساله بنجاح.")

async def main():
    scanner = CryptoScanner()
    symbols = scanner.get_top_300_symbols()
    
    final_report_list = []
    for i, symbol in enumerate(symbols):
        print(f"[{i+1}/300] فحص {symbol}...")
        res = scanner.run_backtest(symbol)
        if res:
            final_report_list.append(res)
    
    await send_to_telegram(final_report_list)

if __name__ == "__main__":
    asyncio.run(main())
