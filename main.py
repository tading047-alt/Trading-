import ccxt
import pandas as pd
import numpy as np
import asyncio
from telegram import Bot

# --- الإعدادات ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class MarketPulseEngine:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.wallet = 1000.0
        self.trade_amount = 100.0
        self.min_volume = 5000000  # 5 مليون دولار لفتح الفرص
        self.entry_score = 75      # 75 كحد أدنى للدخول

    def calculate_indicators(self, df):
        # RSI & EMA 100 (أسرع من 200)
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain/loss)))
        df['ema100'] = df['c'].ewm(span=100).mean()
        # Bollinger Bandwidth
        df['sma20'] = df['c'].rolling(20).mean()
        df['std'] = df['c'].rolling(20).std()
        df['bw'] = (df['std'] * 4) / df['sma20']
        # ATR
        df['tr'] = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
        df['atr'] = df['tr'].rolling(14).mean()
        return df

    def get_pulse_score(self, df, i):
        score = 0
        # 1. سيولة شرائية (أكثر من المتوسط بـ 1.5 مرة فقط بدل 2.5)
        if df['v'].iloc[i] > df['v'].iloc[max(0, i-20):i].mean() * 1.5: score += 25
        # 2. اتجاه إيجابي (فوق EMA 100)
        if df['c'].iloc[i] > df['ema100'].iloc[i]: score += 25
        # 3. زخم RSI (بين 50 و 75)
        if 50 < df['rsi'].iloc[i] < 75: score += 25
        # 4. انفجار ضيق (أقل من المتوسط بـ 1.1 مرة)
        if df['bw'].iloc[i] < df['bw'].iloc[max(0, i-20):i].mean(): score += 25
        return score

    async def backtest_symbol(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=740)
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            # فلتر سيولة لحظي
            if (df['v'].iloc[-1] * df['c'].iloc[-1]) < self.min_volume: return []
            
            df = self.calculate_indicators(df)
            trades = []
            
            for i in range(20, len(df) - 24):
                if self.get_pulse_score(df, i) >= self.entry_score:
                    entry_p = df['c'].iloc[i]
                    atr = df['atr'].iloc[i]
                    # أهداف أكثر واقعية (1.5 ربح مقابل 1 خسارة)
                    tp = entry_p + (atr * 1.5)
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
        await self.bot.send_message(chat_id=CHAT_ID, text="⚡ تشغيل محاكي 'نبض السوق'...\n🎯 توسيع الفلاتر (سكور 75) لاكتشاف حجم صفقات أكبر.")
        markets = self.exchange.load_markets()
        symbols = [s for s in markets if '/USDT' in s and markets[s]['active']][:800]
        
        all_trades = []
        for i in range(0, len(symbols), 50):
            batch = symbols[i:i+50]
            tasks = [self.backtest_symbol(sym) for sym in batch]
            res = await asyncio.gather(*tasks)
            for r in res: all_trades.extend(r)
            await asyncio.sleep(1)

        if all_trades:
            for t in all_trades:
                # خصم 0.2% رسوم تبادل من كل صفقة لجعل النتيجة حقيقية
                actual_pnl = t['pnl'] - 0.2 
                self.wallet += (self.trade_amount * (actual_pnl / 100))
            
            wins = len([t for t in all_trades if t['res'] == 'WIN'])
            win_rate = (wins / len(all_trades)) * 100
            
            summary = (
                f"📊 **نتائج نبض السوق (V21):**\n\n"
                f"💰 الرصيد النهائي: {self.wallet:.2f}$\n"
                f"📈 العائد (بعد الرسوم): {((self.wallet-1000)/1000)*100:.2f}%\n"
                f"🎯 عدد الصفقات المكتشفة: {len(all_trades)}\n"
                f"⚖️ نسبة النجاح: {win_rate:.2f}%"
            )
            await self.bot.send_message(chat_id=CHAT_ID, text=summary)
        else:
            await self.bot.send_message(chat_id=CHAT_ID, text="❌ لم تنجح المحاولة. جاري فحص الكود.")

if __name__ == "__main__":
    asyncio.run(MarketPulseEngine().run())
