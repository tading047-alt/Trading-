import ccxt
import pandas as pd
import pandas_ta as ta # مكتبة متطورة للمؤشرات
import asyncio
from telegram import Bot

# --- الإعدادات ---
TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class AdvancedScorer:
    def __init__(self, df):
        self.df = df
        self.score = 0
        self.details = []

    def calculate_all(self):
        # 1. انخناق بولنجر (Squeeze)
        bb = ta.bbands(self.df['close'], length=20, std=2)
        bb_width = bb['BBU_20_2.0'] - self.bb['BBL_20_2.0']
        if bb_width.iloc[-1] < bb_width.rolling(50).mean().iloc[-1]:
            self.score += 10
            self.details.append("BB-Squeeze")

        # 2. سيولة كبيرة (Volume Spike)
        avg_vol = self.df['volume'].rolling(20).mean().iloc[-1]
        if self.df['volume'].iloc[-1] > avg_vol * 2.5:
            self.score += 10
            self.details.append("High-Volume")

        # 3. التقاطع الذهبي (Golden Cross)
        sma50 = ta.sma(self.df['close'], length=50).iloc[-1]
        sma200 = ta.sma(self.df['close'], length=200).iloc[-1]
        if sma50 > sma200:
            self.score += 10
            self.details.append("Golden-Cross")

        # 4. دايفرجنس RSI (تبسيط برمجياً)
        rsi = ta.rsi(self.df['close'], length=14)
        if self.df['close'].iloc[-1] < self.df['close'].iloc[-10] and rsi.iloc[-1] > rsi.iloc[-10]:
            self.score += 10
            self.details.append("RSI-Divergence")

        # 5. الأموال الذكية (Order Block Detection)
        # إذا كان السعر الحالي يلمس أدنى سعر في آخر 50 شمعة مع ارتداد
        if self.df['low'].iloc[-1] <= self.df['low'].rolling(50).min().iloc[-1]:
            self.score += 10
            self.details.append("SMC-DemandZone")

        return self.score, ", ".join(self.details)

async def main():
    exchange = ccxt.binance()
    tickers = exchange.fetch_tickers()
    symbols = [s[0] for s in sorted(tickers.items(), key=lambda x: x[1].get('quoteVolume', 0), reverse=True) if '/USDT' in s[0]][:100] # فحص أفضل 100 لتوفير الوقت

    final_results = []

    for symbol in symbols:
        try:
            print(f"جاري تحليل {symbol}...")
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=250)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            scorer = AdvancedScorer(df)
            score, reasons = scorer.calculate_all()
            
            final_results.append({
                'Symbol': symbol,
                'Score': score,
                'Reasons': reasons,
                'Price': df['close'].iloc[-1]
            })
        except:
            continue

    # إرسال تقرير بالعملات التي سكورها عالي (> 30)
    df_final = pd.DataFrame(final_results).sort_values(by='Score', ascending=False)
    top_picks = df_final[df_final['Score'] >= 30]

    report = "🎯 رادار العملات بنظام السكور الذكي\n\n"
    for _, row in top_picks.head(10).iterrows():
        report += f"💎 {row['Symbol']} | Score: {row['Score']}/50\n"
        report += f"📡 المؤشرات: {row['Reasons']}\n\n"

    bot = Bot(token=TOKEN)
    async with bot:
        await bot.send_message(chat_id=CHAT_ID, text=report)
        df_final.to_csv("Detailed_Score_Report.csv", index=False)
        with open("Detailed_Score_Report.csv", 'rb') as f:
            await bot.send_document(chat_id=CHAT_ID, document=f)

if __name__ == "__main__":
    asyncio.run(main())
