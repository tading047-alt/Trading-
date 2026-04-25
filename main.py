import ccxt
import pandas as pd
import pandas_ta as ta
import backtrader as bt
import asyncio
import os
from telegram import Bot
from datetime import datetime, timedelta

# --- إعدادات التلغرام ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class AdvancedScoreStrategy(bt.Strategy):
    params = (
        ('stop_loss', 0.02),    # 2% وقف خسارة
        ('take_profit', 0.04),  # 4% جني أرباح
        ('score_threshold', 30), # الحد الأدنى للدخول
    )

    def __init__(self):
        # المؤشرات الفنية
        self.sma50 = bt.indicators.SMA(self.data.close, period=50)
        self.sma200 = bt.indicators.SMA(self.data.close, period=200)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20)
        self.atr = bt.indicators.ATR(self.data, period=20)
        
        # متغيرات تسجيل الصفقة
        self.trade_data = {
            'entry_date': "N/A",
            'entry_hour': "N/A",
            'entry_price': 0,
            'exit_price': 0,
            'score': 0,
            'status': "No Trade" # Win, Loss, or Open
        }

    def calculate_score(self):
        score = 0
        # 1. انخناق البولنجر
        if (self.bb.top[0] - self.bb.bot[0]) < (self.atr[0] * 1.5): score += 10
        # 2. التقاطع الذهبي
        if self.sma50[0] > self.sma200[0]: score += 10
        # 3. دايفرجنس RSI (تبسيط: RSI منخفض مع زخم صاعد)
        if self.rsi[0] < 40 and self.rsi[0] > self.rsi[-1]: score += 10
        # 4. اختراق السعر للبولنجر العلوي (تأكيد الانفجار)
        if self.data.close[0] > self.bb.top[0]: score += 10
        # 5. سيولة عالية (حجم تداول أعلى من المتوسط)
        if self.data.volume[0] > bt.indicators.SMA(self.data.volume, period=20)[0] * 1.5: score += 10
        return score

    def next(self):
        if not self.position:
            current_score = self.calculate_score()
            if current_score >= self.p.score_threshold:
                self.trade_data['score'] = current_score
                self.trade_data['entry_price'] = self.data.close[0]
                self.trade_data['entry_date'] = bt.num2date(self.data.datetime[0]).strftime('%Y-%m-%d')
                self.trade_data['entry_hour'] = bt.num2date(self.data.datetime[0]).strftime('%H:%M')
                
                # وضع أوامر الوقف والهدف
                stop_price = self.data.close[0] * (1.0 - self.p.stop_loss)
                limit_price = self.data.close[0] * (1.0 + self.p.take_profit)
                
                self.buy(exectype=bt.Order.Market)
                # تسجيل الأهداف (محاكاة يدوية داخل next لسهولة التقرير)
                self.stop_p = stop_price
                self.limit_p = limit_price
        else:
            # التحقق من شروط الخروج (SL أو TP)
            if self.data.low[0] <= self.stop_p:
                self.trade_data['status'] = "Loss (-2%)"
                self.trade_data['exit_price'] = self.stop_p
                self.close()
            elif self.data.high[0] >= self.limit_p:
                self.trade_data['status'] = "Win (+4%)"
                self.trade_data['exit_price'] = self.limit_p
                self.close()

class BacktestManager:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})

    def run(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=300)
            df = pd.DataFrame(ohlcv, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['datetime'], unit='ms')
            
            cerebro = bt.Cerebro()
            cerebro.addstrategy(AdvancedScoreStrategy)
            data = bt.feeds.PandasData(dataname=df.set_index('datetime'))
            cerebro.adddata(data)
            cerebro.broker.setcash(1000.0)
            
            results = cerebro.run()
            strat = results[0]
            
            res = strat.trade_data
            res['Symbol'] = symbol
            # حساب الربح النهائي الصافي للمحفظة في هذه العملة
            res['Final_Account_Value'] = round(cerebro.broker.getvalue(), 2)
            return res
        except:
            return None

async def main():
    manager = BacktestManager()
    # جلب أفضل 300 عملة
    tickers = manager.exchange.fetch_tickers()
    symbols = [s[0] for s in sorted(tickers.items(), key=lambda x: x[1].get('quoteVolume', 0), reverse=True) if '/USDT' in s[0]][:300]
    
    print(f"🚀 بدء باكتيست 300 عملة مع SL 2% و TP 4%...")
    all_results = []
    for i, sym in enumerate(symbols):
        print(f"[{i+1}/300] جاري فحص {sym}...")
        report = manager.run(sym)
        if report: all_results.append(report)
    
    # إنشاء ملف CSV
    df_final = pd.DataFrame(all_results)
    file_name = "Final_Backtest_Scoring.csv"
    df_final.to_csv(file_name, index=False)
    
    # إرسال تلغرام
    bot = Bot(token=TELEGRAM_TOKEN)
    summary = f"🏁 انتهى الباكتيست لـ 300 عملة\n\n"
    summary += f"✅ صفقات ناجحة (Win): {len(df_final[df_final['status'] == 'Win (+4%)'])}\n"
    summary += f"❌ صفقات خاسرة (Loss): {len(df_final[df_final['status'] == 'Loss (-2%)'])}\n"

    async with bot:
        await bot.send_message(chat_id=CHAT_ID, text=summary)
        with open(file_name, 'rb') as f:
            await bot.send_document(chat_id=CHAT_ID, document=f, caption="تقرير مفصل: سكور، أهداف، ونتائج 📄")

if __name__ == "__main__":
    asyncio.run(main())
