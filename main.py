import ccxt
import pandas as pd
import numpy as np
import asyncio
from telegram import Bot

# --- الإعدادات ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class SniperEngine:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.wallet = 1000.0
        self.trade_amount = 100.0
        self.entry_score = 82 # العودة للدقة

    def calculate_indicators(self, df):
        # RSI & EMA 200
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain/loss)))
        df['ema200'] = df['c'].ewm(span=200).mean()
        # ATR
        df['tr'] = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
        df['atr'] = df['tr'].rolling(14).mean()
        # Bollinger
        df['sma20'] = df['c'].rolling(20).mean()
        df['std'] = df['c'].rolling(20).std()
        df['bw'] = (df['std'] * 4) / df['sma20']
        return df

    def get_sniper_score(self, df, i):
        score = 0
        if df['v'].iloc[i] > df['v'].iloc[max(0, i-20):i].mean() * 3.0: score += 25 # حجم تداول ضخم
        if df['c'].iloc[i] > df['ema200'].iloc[i]: score += 25                   # اتجاه صاعد قوي
        if 60 < df['rsi'].iloc[i] < 75: score += 25                             # زخم شرائي حقيقي
        if df['bw'].iloc[i] < df['bw'].iloc[max(0, i-50):i].min() * 1.3: score += 25 # انفجار من ضيق
        return score

    async def backtest_symbol(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=740)
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            df = self.calculate_indicators(df)
            trades = []
            for i in range(50, len(df) - 24):
                if self.get_sniper_score(df, i) >= self.entry_score:
                    entry_p = df['c'].iloc[i]
                    atr = df['atr'].iloc[i]
                    # نسبة مخاطرة عالية (ربح 3 مقابل خسارة 1)
                    tp = entry_p + (atr * 3.0)
                    sl = entry_p - (atr * 1.0)
                    for j in range(i + 1, min(i + 48, len(df))):
                        if df['h'].iloc[j] >= tp:
                            trades.append({'res': 'WIN', 'pnl': ((tp/entry_p)-1)*100})
                            i = j; break
                        if df['l'].iloc[j] <= sl:
                            trades.append({'res': 'LOSS', 'pnl': ((sl/entry_p)-1)*100})
                            i = j; break
            return trades
        except: return []

    async def run(self):
        await self.bot.send_message(chat_id=CHAT_ID, text="🎯 تشغيل نظام 'القناص'...\n🛠️ تعديل R:R لـ 3:1 وتقليل عدد الصفقات لخفض الرسوم.")
        markets = self.exchange.load_markets()
        symbols = [s for s in markets if '/USDT' in s and markets[s]['active']][:800]
        all_trades = []
        for i in range(0, len(symbols), 50):
            batch = symbols[i:i+50]
            tasks = [self.backtest_symbol(sym) for sym in batch]
            res = await asyncio.gather(*tasks)
            for r in res: all_trades.extend(r)
        
        if all_trades:
            for t in all_trades:
                # خصم الرسوم 0.2%
                self.wallet += (self.trade_amount * ((t['pnl'] - 0.2) / 100))
            
            summary = (
                f"📊 **نتائج القناص (V22):**\n\n"
                f"💰 الرصيد النهائي: {self.wallet:.2f}$\n"
                f"📈 العائد الصافي: {((self.wallet-1000)/1000)*100:.2f}%\n"
                f"🎯 عدد الصفقات: {len(all_trades)}\n"
                f"⚖️ نسبة النجاح: {(len([x for x in all_trades if x['res']=='WIN'])/len(all_trades)*100):.2f}%"
            )
            await self.bot.send_message(chat_id=CHAT_ID, text=summary)

if __name__ == "__main__":
    asyncio.run(SniperEngine().run())
