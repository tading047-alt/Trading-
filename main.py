import ccxt
import pandas as pd
import numpy as np
import asyncio
from telegram import Bot
from datetime import datetime

# --- الإعدادات ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class FullMonthlyBacktester:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.all_trades = [] # لتخزين كل صفقة تمت في الشهر لـ 800 عملة

    def get_indicators(self, df):
        # حساب المؤشرات: BB, RSI, ATR, EMA
        df['sma20'] = df['c'].rolling(20).mean()
        df['std'] = df['c'].rolling(20).std()
        df['bw'] = (df['std'] * 4) / df['sma20']
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain/loss)))
        df['tr'] = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
        df['atr'] = df['tr'].rolling(14).mean()
        df['ema50'] = df['c'].ewm(span=50).mean()
        df['ema200'] = df['c'].ewm(span=200).mean()
        return df

    def get_score(self, df, i):
        score = 0
        if df['bw'].iloc[i] < df['bw'].iloc[max(0, i-100):i].min() * 1.2: score += 20
        if df['c'].iloc[i] > df['ema50'].iloc[i] > df['ema200'].iloc[i]: score += 20
        if 50 < df['rsi'].iloc[i] < 70: score += 20
        if df['v'].iloc[i] > df['v'].iloc[max(0, i-20):i].mean() * 2.5: score += 20
        if df['h'].iloc[i-2] < df['l'].iloc[i]: score += 20
        return score

    async def backtest_symbol(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=740)
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            df = self.get_indicators(df)
            
            symbol_trades = []
            for i in range(100, len(df) - 24):
                if self.get_score(df, i) >= 80:
                    entry_time = datetime.fromtimestamp(df['t'].iloc[i]/1000).strftime('%Y-%m-%d %H:%M')
                    entry_price = df['c'].iloc[i]
                    tp = entry_price + (df['atr'].iloc[i] * 2.5)
                    sl = entry_price - (df['atr'].iloc[i] * 1.5)
                    
                    result = "Pending"
                    for j in range(i + 1, min(i + 48, len(df))):
                        if df['h'].iloc[j] >= tp:
                            result = "WIN"
                            i = j; break
                        if df['l'].iloc[j] <= sl:
                            result = "LOSS"
                            i = j; break
                    
                    if result != "Pending":
                        symbol_trades.append({
                            'Time': entry_time,
                            'Symbol': symbol,
                            'Result': result,
                            'Entry': entry_price,
                            'Score': self.get_score(df, i)
                        })
            return symbol_trades
        except: return []

    async def run_full_test(self):
        await self.bot.send_message(chat_id=CHAT_ID, text="📊 بدأ استخراج تقرير جميع الصفقات لـ 800 عملة (آخر 30 يوماً)...")
        
        markets = self.exchange.load_markets()
        symbols = [s for s in markets if '/USDT' in s and markets[s]['active']][:800]
        
        total_results = []
        for i in range(0, len(symbols), 40):
            batch = symbols[i:i+40]
            tasks = [self.backtest_symbol(sym) for sym in batch]
            res = await asyncio.gather(*tasks)
            for r in res: total_results.extend(r)
            print(f"تمت معالجة {min(i+40, 800)} عملة...")
            await asyncio.sleep(1)

        if total_results:
            df_trades = pd.DataFrame(total_results)
            wins = len(df_trades[df_trades['Result'] == 'WIN'])
            losses = len(df_trades[df_trades['Result'] == 'LOSS'])
            win_rate = (wins / (wins + losses)) * 100
            
            filename = "Global_Monthly_Backtest.csv"
            df_trades.to_csv(filename, index=False)
            
            summary = (
                f"✅ **نتيجة الـ Backtesting لجميع العملات (شهر):**\n\n"
                f"🔹 إجمالي الصفقات المكتشفة: {len(df_trades)}\n"
                f"✅ الصفقات الناجحة: {wins}\n"
                f"❌ الصفقات الفاشلة: {losses}\n"
                f"📈 نسبة النجاح الكلية: {win_rate:.2f}%\n\n"
                f"📂 تم إرفاق ملف بجميع الصفقات التفصيلية."
            )
            await self.bot.send_message(chat_id=CHAT_ID, text=summary, parse_mode='Markdown')
            with open(filename, 'rb') as f:
                await self.bot.send_document(chat_id=CHAT_ID, document=f)

if __name__ == "__main__":
    asyncio.run(FullMonthlyBacktester().run_full_test())
