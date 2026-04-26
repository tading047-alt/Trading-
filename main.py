import ccxt
import pandas as pd
import numpy as np
import asyncio
from telegram import Bot

# --- الإعدادات ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class GoldenBalanceEngine:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.wallet = 1000.0
        self.trade_amount = 100.0
        # تخفيف الفلاتر قليلاً للسماح بفرص أكثر
        self.min_volume = 8000000  # 8 مليون دولار بدل 15
        self.entry_score = 85      # 85 بدل 90

    def calculate_indicators(self, df):
        # RSI & EMA
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain/loss)))
        df['ema200'] = df['c'].ewm(span=200).mean()
        # Bollinger Bandwidth
        df['sma20'] = df['c'].rolling(20).mean()
        df['std'] = df['c'].rolling(20).std()
        df['bw'] = (df['std'] * 4) / df['sma20']
        # ATR للاهداف الديناميكية
        df['tr'] = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
        df['atr'] = df['tr'].rolling(14).mean()
        return df

    def get_balanced_score(self, df, i):
        score = 0
        if df['bw'].iloc[i] < df['bw'].iloc[max(0, i-50):i].min() * 1.2: score += 20
        if df['c'].iloc[i] > df['ema200'].iloc[i]: score += 20
        if 45 < df['rsi'].iloc[i] < 70: score += 20 # توسيع نطاق RSI
        if df['v'].iloc[i] > df['v'].iloc[max(0, i-20):i].mean() * 2.0: score += 20
        if df['h'].iloc[i-2] < df['l'].iloc[i]: score += 20
        return score

    async def backtest_symbol(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=740)
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            if (df['v'].iloc[-1] * df['c'].iloc[-1]) < self.min_volume: return []
            
            df = self.calculate_indicators(df)
            trades = []
            
            for i in range(50, len(df) - 24):
                if self.get_balanced_score(df, i) >= self.entry_score:
                    entry_p = df['c'].iloc[i]
                    atr = df['atr'].iloc[i]
                    # أهداف تعتمد على تذبذب العملة نفسها
                    tp = entry_p + (atr * 2.5)
                    sl = entry_p - (atr * 1.5)
                    
                    for j in range(i + 1, min(i + 48, len(df))):
                        if df['h'].iloc[j] >= tp:
                            trades.append({'res': 'WIN', 'pnl': (tp/entry_p - 1) * 100})
                            i = j; break
                        if df['l'].iloc[j] <= sl:
                            trades.append({'res': 'LOSS', 'pnl': (sl/entry_p - 1) * 100})
                            i = j; break
            return trades
        except: return []

    async def run(self):
        await self.bot.send_message(chat_id=CHAT_ID, text="⚖️ تشغيل نظام 'التوازن الذهبي'...\n🔄 خفض السكور لـ 85 وتعديل فلاتر السيولة لجلب صفقات حقيقية.")
        markets = self.exchange.load_markets()
        symbols = [s for s in markets if '/USDT' in s and markets[s]['active']][:600]
        
        all_trades = []
        for i in range(0, len(symbols), 50):
            batch = symbols[i:i+50]
            tasks = [self.backtest_symbol(sym) for sym in batch]
            res = await asyncio.gather(*tasks)
            for r in res: all_trades.extend(r)
            await asyncio.sleep(1)

        if all_trades:
            for t in all_trades:
                self.wallet += (self.trade_amount * (t['pnl'] / 100))
            
            wins = len([t for t in all_trades if t['res'] == 'WIN'])
            win_rate = (wins / len(all_trades)) * 100
            
            summary = (
                f"📊 **نتائج التوازن الذهبي:**\n\n"
                f"💰 الرصيد النهائي: {self.wallet:.2f}$\n"
                f"📈 العائد: {((self.wallet-1000)/1000)*100:.2f}%\n"
                f"🎯 عدد الصفقات: {len(all_trades)}\n"
                f"⚖️ نسبة النجاح: {win_rate:.2f}%"
            )
            await self.bot.send_message(chat_id=CHAT_ID, text=summary)
        else:
            await self.bot.send_message(chat_id=CHAT_ID, text="❌ لم يتم العثور على صفقات. جاري مراجعة الشروط.")

if __name__ == "__main__":
    asyncio.run(GoldenBalanceEngine().run())
