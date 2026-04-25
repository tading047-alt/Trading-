import ccxt
import pandas as pd
import backtrader as bt
import asyncio
from telegram import Bot
from datetime import datetime

# --- الإعدادات ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class UltimateEliteStrategy(bt.Strategy):
    params = (
        ('atr_period', 14),
        ('atr_multiplier', 2.0),
        ('min_score', 70),
    )

    def __init__(self):
        # 1. المؤشرات الأساسية
        self.ema9 = bt.indicators.EMA(period=9)
        self.ema21 = bt.indicators.EMA(period=21)
        self.ema50 = bt.indicators.EMA(period=50)
        self.ema200 = bt.indicators.EMA(period=200)
        self.rsi = bt.indicators.RSI(period=14)
        self.atr = bt.indicators.ATR(period=self.p.atr_period)
        self.vol_sma = bt.indicators.SMA(self.data.volume, period=20)
        
        # 2. متغيرات التتبع
        self.trade_results = {'score': 0, 'details': "", 'status': "No Trade", 'profit_pct': 0}

    def calculate_advanced_score(self):
        score = 0
        reasons = []

        # أ- فلتر الاتجاه (25 نقطة)
        if self.ema9[0] > self.ema21[0] > self.ema50[0] > self.ema200[0]:
            score += 25; reasons.append("Trend_OK")

        # ب- الشمعة الابتلاعية Bullish Engulfing (15 نقطة)
        # إذا كانت الشمعة الحالية خضراء وتغطي جسم الشمعة السابقة الحمراء
        if self.data.close[0] > self.data.open[-1] and self.data.open[0] < self.data.close[-1] and self.data.close[-1] < self.data.open[-1]:
            score += 15; reasons.append("Engulfing")

        # ج- المسافة عن القمة (15 نقطة)
        # البحث عن أعلى سعر في آخر 30 شمعة (High of 30 periods)
        recent_high = max([self.data.high[-i] for i in range(1, 31)])
        if self.data.close[0] >= (recent_high * 0.95): # ضمن مسافة 5% من القمة
            score += 15; reasons.append("Near_ATH")

        # د- فوليوم الحيتان (20 نقطة)
        if self.data.volume[0] > self.vol_sma[0] * 2.5:
            score += 20; reasons.append("Whale_Vol")

        # هـ- قوة RSI (15 نقطة)
        if 55 < self.rsi[0] < 75:
            score += 15; reasons.append("RSI_Power")

        # و- ساعة الذروة (10 نقاط)
        curr_hour = bt.num2date(self.data.datetime[0]).hour
        if 8 <= curr_hour <= 17:
            score += 10; reasons.append("London_NY_Session")

        return score, "|".join(reasons)

    def next(self):
        if not self.position:
            s, d = self.calculate_advanced_score()
            if s >= self.p.min_score:
                self.buy()
                self.entry_price = self.data.close[0]
                self.max_price = self.data.close[0]
                self.trade_results.update({'score': s, 'details': d})
        else:
            self.max_price = max(self.max_price, self.data.high[0])
            trailing_stop = self.max_price - (self.atr[0] * self.p.atr_multiplier)
            if self.data.low[0] <= trailing_stop:
                self.close()
                profit = (trailing_stop - self.entry_price) / self.entry_price
                self.trade_results['status'] = "Win" if profit > 0 else "Loss"
                self.trade_results['profit_pct'] = round(profit * 100, 2)

async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text="🚀 إطلاق الرادار المطور V3 (Engulfing + Price Action)\n🔍 جاري مسح 800 عملة على دفعات...")

    exchange = ccxt.binance({'enableRateLimit': True})
    markets = exchange.load_markets()
    symbols = [s for s in markets if '/USDT' in s and markets[s]['active']][:800]
    
    final_data = []
    batch_size = 50
    
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i+batch_size]
        for sym in batch:
            try:
                ohlcv = exchange.fetch_ohlcv(sym, timeframe='1h', limit=400)
                df = pd.DataFrame(ohlcv, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
                df['datetime'] = pd.to_datetime(df['datetime'], unit='ms')
                
                cerebro = bt.Cerebro()
                cerebro.addstrategy(UltimateEliteStrategy)
                data = bt.feeds.PandasData(dataname=df.set_index('datetime'))
                cerebro.adddata(data)
                
                results = cerebro.run()
                res = results[0].trade_results
                if res['score'] >= 70:
                    res['Symbol'] = sym
                    # إضافة سكور إضافي للقوة النسبية
                    btc_t = exchange.fetch_ticker('BTC/USDT')
                    coin_t = exchange.fetch_ticker(sym)
                    res['Strength'] = "Bullish_Leader" if coin_t['percentage'] > btc_t['percentage'] else "Follower"
                    final_data.append(res)
                
                await asyncio.sleep(0.02) # سرعة التنفيذ مع حماية Rate Limit
            except: continue

        await bot.send_message(chat_id=CHAT_ID, text=f"⏳ تمت معالجة {i+len(batch)} عملة...\n💎 صفقات ذهبية مكتشفة حتى الآن: {len(final_data)}")
        await asyncio.sleep(20) # استراحة لضمان عدم الحظر

    if final_data:
        df_final = pd.DataFrame(final_data).sort_values(by='score', ascending=False)
        file_name = "Elite_V3_Report.csv"
        df_final.to_csv(file_name, index=False)
        
        summary = f"🏁 اكتمل التحليل الشامل!\n🔥 تم العثور على {len(final_data)} فرصة بسكور عالٍ.\n📥 التقرير المرفق يحتوي على تفاصيل Engulfing و Near_ATH."
        await bot.send_message(chat_id=CHAT_ID, text=summary)
        with open(file_name, 'rb') as f:
            await bot.send_document(chat_id=CHAT_ID, document=f)
    else:
        await bot.send_message(chat_id=CHAT_ID, text="⚠️ انتهى المسح: السوق حالياً لا يقدم فرصاً بنظام سكور 70+.")

if __name__ == "__main__":
    asyncio.run(main())
