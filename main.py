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

# --- 1. استراتيجية التداول الكمي المتقدمة ---
class UltimateInstitutionalStrategy(bt.Strategy):
    params = (
        ('atr_period', 14),
        ('atr_multiplier', 2.0), # الوقف يبتعد بمقدار 2 ATR عن القمة
        ('min_score', 50),       # تقليل السكور قليلاً لضمان العثور على صفقات في الباكتيست
    )

    def __init__(self):
        # فلاتر الاتجاه (EMAs)
        self.ema9 = bt.indicators.EMA(period=9)
        self.ema21 = bt.indicators.EMA(period=21)
        self.ema50 = bt.indicators.EMA(period=50)
        self.ema200 = bt.indicators.EMA(period=200)
        
        # مؤشرات الزخم والسيولة
        self.adx = bt.indicators.ADX(period=14)
        self.rsi = bt.indicators.RSI(period=14)
        self.macd = bt.indicators.MACD()
        self.bb = bt.indicators.BollingerBands(period=20)
        self.atr = bt.indicators.ATR(period=self.p.atr_period)
        self.vol_sma = bt.indicators.SMA(self.data.volume, period=20)

        # متغيرات تتبع الصفقة
        self.entry_price = None
        self.max_price = 0
        self.trade_results = {
            'score': 0, 'details': "", 'status': "No Trade",
            'profit_pct': 0, 'entry_price': 0, 'exit_price': 0
        }

    def calculate_score(self):
        score = 0
        reasons = []

        # أ- فلتر الاتجاه الصاعد (30 نقطة)
        if self.ema9[0] > self.ema21[0] > self.ema50[0] > self.ema200[0]:
            score += 30; reasons.append("Trend_Stacked")

        # ب- قوة الاتجاه ADX (15 نقطة)
        if self.adx[0] > 25:
            score += 15; reasons.append("Strong_ADX")

        # ج- انخناق البولنجر (15 نقطة)
        if (self.bb.top[0] - self.bb.bot[0]) < (self.atr[0] * 2):
            score += 15; reasons.append("Squeeze")

        # د- فوليوم الحيتان (20 نقطة)
        if self.data.volume[0] > self.vol_sma[0] * 2.5:
            score += 20; reasons.append("Whale_Volume")

        # هـ- فلتر الوقت (10 نقاط)
        current_hour = bt.num2date(self.data.datetime[0]).hour
        if 8 <= current_hour <= 18: 
            score += 10; reasons.append("Prime_Session")

        # و- زخم RSI و MACD (10 نقاط)
        if self.rsi[0] > 50 and self.macd.macd[0] > self.macd.signal[0]:
            score += 10; reasons.append("Momentum_Confirm")

        return score, "|".join(reasons)

    def next(self):
        if not self.position:
            s, d = self.calculate_score()
            if s >= self.p.min_score:
                self.buy()
                self.entry_price = self.data.close[0]
                self.max_price = self.data.close[0]
                self.trade_results.update({'score': s, 'details': d, 'entry_price': self.entry_price})
        else:
            self.max_price = max(self.max_price, self.data.high[0])
            # الوقف المتحرك المعتمد على ATR
            trailing_stop = self.max_price - (self.atr[0] * self.p.atr_multiplier)
            
            if self.data.low[0] <= trailing_stop:
                self.close()
                self.trade_results['exit_price'] = trailing_stop
                profit = (trailing_stop - self.entry_price) / self.entry_price
                self.trade_results['status'] = "Win" if profit > 0 else "Loss"
                self.trade_results['profit_pct'] = round(profit * 100, 2)

# --- 2. محرك المسح والباكتيست ---
class CryptoQuantScanner:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})

    def run_backtest(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=500)
            df = pd.DataFrame(ohlcv, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['datetime'], unit='ms')
            
            cerebro = bt.Cerebro()
            cerebro.addstrategy(UltimateInstitutionalStrategy)
            data = bt.feeds.PandasData(dataname=df.set_index('datetime'))
            cerebro.adddata(data)
            cerebro.broker.setcash(1000.0)
            
            results = cerebro.run()
            res = results[0].trade_results
            res['Symbol'] = symbol
            return res
        except: return None

# --- 3. الدالة الرئيسية للتشغيل والإرسال ---
async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    # رسالة فورية للتأكد من الاتصال
    try:
        await bot.send_message(chat_id=CHAT_ID, text="⚙️ بدأ الرادار الكمي النهائي...\n🎯 الهدف: فحص 300 عملة.\n🛠️ الفلاتر: ATR Trailing, Whale Volume, BTC Strength.")
    except Exception as e:
        print(f"Error: Telegram Chat ID or Token is invalid: {e}")
        return

    scanner = CryptoQuantScanner()
    
    # جلب أداء البيتكوين للمقارنة
    try:
        btc_ticker = scanner.exchange.fetch_ticker('BTC/USDT')
        btc_change = btc_ticker['percentage']
    except: btc_change = 0

    tickers = scanner.exchange.fetch_tickers()
    symbols = [s[0] for s in sorted(tickers.items(), key=lambda x: x[1].get('quoteVolume', 0), reverse=True) if '/USDT' in s[0]][:300]
    
    final_data = []
    for i, sym in enumerate(symbols):
        print(f"[{i+1}/300] Analyzing: {sym}")
        res = scanner.run_backtest(sym)
        if res and res['score'] > 0:
            # إضافة فلتر القوة النسبية
            try:
                coin_ticker = scanner.exchange.fetch_ticker(sym)
                res['BTC_Rel_Strength'] = "Stronger" if coin_ticker['percentage'] > btc_change else "Weaker"
            except: res['BTC_Rel_Strength'] = "N/A"
            final_data.append(res)
        
        # إرسال تحديث كل 100 عملة لضمان استمرار العمل
        if (i + 1) % 100 == 0:
            await bot.send_message(chat_id=CHAT_ID, text=f"⏳ تم فحص {i+1}/300 عملة بنجاح...")

    if final_data:
        df = pd.DataFrame(final_data).sort_values(by='score', ascending=False)
        file_name = "Final_Quant_Backtest.csv"
        df.to_csv(file_name, index=False)
        
        msg = f"🏁 اكتمل الباكتيست!\n✅ صفقات مسجلة: {len(df[df['status'] != 'No Trade'])}\n⭐ أعلى سكور محقق: {df['score'].max()}"
        await bot.send_message(chat_id=CHAT_ID, text=msg)
        with open(file_name, 'rb') as f:
            await bot.send_document(chat_id=CHAT_ID, document=f, caption="تقرير السكور الكمي والوقف المتحرك 📄")
    else:
        await bot.send_message(chat_id=CHAT_ID, text="⚠️ انتهى الفحص ولم يتم العثور على صفقات تطابق الشروط (جرب تقليل min_score).")

if __name__ == "__main__":
    asyncio.run(main())
