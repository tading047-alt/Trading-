import ccxt
import pandas as pd
import numpy as np
import asyncio
from telegram import Bot
from datetime import datetime

# --- الإعدادات ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class MidRangeBacktester:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.balance = 1000.0
        self.trade_size = 100.0
        self.blacklist = ['BTC/USDT', 'ETH/USDT', 'USDC/USDT', 'DAI/USDT', 'FDUSD/USDT']

    def calculate_indicators(self, df):
        # Bollinger Bands
        df['sma20'] = df['c'].rolling(20).mean()
        df['std'] = df['c'].rolling(20).std()
        df['bw'] = (df['std'] * 4) / df['sma20']
        # RSI
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain/loss)))
        # EMA & ATR
        df['ema200'] = df['c'].ewm(span=200).mean()
        df['tr'] = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
        df['atr'] = df['tr'].rolling(14).mean()
        return df

    def get_detailed_score(self, df, i):
        score = 0
        active_strats = []
        if df['bw'].iloc[i] < df['bw'].iloc[max(0, i-50):i].min() * 1.15: 
            score += 20; active_strats.append("Squeeze")
        if df['c'].iloc[i] > df['ema200'].iloc[i]: 
            score += 20; active_strats.append("Trend")
        if 50 < df['rsi'].iloc[i] < 70: 
            score += 20; active_strats.append("RSI")
        if df['v'].iloc[i] > df['v'].iloc[max(0, i-20):i].mean() * 2.2: 
            score += 20; active_strats.append("Volume")
        if df['h'].iloc[i-2] < df['l'].iloc[i]: 
            score += 20; active_strats.append("FVG")
        
        return score, ",".join(active_strats)

    async def backtest_range(self, symbol):
        if any(x in symbol for x in self.blacklist): return []
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=740)
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            df = self.calculate_indicators(df)
            
            symbol_results = []
            for i in range(50, len(df) - 24):
                score, strats = self.get_detailed_score(df, i)
                
                # الفلترة للنطاق المطلوب فقط (80 <= score < 90)
                if 80 <= score < 90:
                    entry_p = df['c'].iloc[i]
                    tp = entry_p * 1.03
                    sl = entry_p * 0.97
                    
                    for j in range(i + 1, min(i + 48, len(df))):
                        if df['h'].iloc[j] >= tp:
                            symbol_results.append({
                                'Time': datetime.fromtimestamp(df['t'].iloc[i]/1000).strftime('%Y-%m-%d %H:%M'),
                                'Symbol': symbol, 'Score': score, 'Strategies': strats,
                                'Entry': entry_p, 'Exit': tp, 'Result': 'WIN', 'PnL': 3.0
                            })
                            i = j; break
                        if df['l'].iloc[j] <= sl:
                            symbol_results.append({
                                'Time': datetime.fromtimestamp(df['t'].iloc[i]/1000).strftime('%Y-%m-%d %H:%M'),
                                'Symbol': symbol, 'Score': score, 'Strategies': strats,
                                'Entry': entry_p, 'Exit': sl, 'Result': 'LOSS', 'PnL': -3.0
                            })
                            i = j; break
            return symbol_results
        except: return []

    async def run(self):
        await self.bot.send_message(chat_id=CHAT_ID, text="🔍 جاري تحليل النطاق (80-89 سكور) لـ 800 عملة...\n📊 سيتم تسجيل كافة التفاصيل الاستراتيجية في ملف CSV.")
        
        markets = self.exchange.load_markets()
        symbols = [s for s in markets if '/USDT' in s and markets[s]['active']][:800]
        
        all_data = []
        for i in range(0, len(symbols), 50):
            batch = symbols[i:i+50]
            tasks = [self.backtest_range(sym) for sym in batch]
            res = await asyncio.gather(*tasks)
            for r in res: all_data.extend(r)
            await asyncio.sleep(1)

        if all_data:
            df = pd.DataFrame(all_data).sort_values(by='Time')
            # محاكاة حركة المحفظة
            for index, row in df.iterrows():
                self.balance += (self.trade_size * (row['PnL'] / 100))
                df.at[index, 'Wallet_Balance'] = self.balance

            wins = len(df[df['Result'] == 'WIN'])
            losses = len(df[df['Result'] == 'LOSS'])
            
            filename = "Range_80_90_Analysis.csv"
            df.to_csv(filename, index=False)
            
            msg = (
                f"📊 **نتائج تحليل النطاق (80-90):**\n\n"
                f"💰 الرصيد النهائي: {self.balance:.2f}$\n"
                f"🎯 عدد الصفقات: {len(df)}\n"
                f"✅ ربح: {wins} | ❌ خسارة: {losses}\n"
                f"⚖️ نسبة النجاح: {(wins/len(df)*100):.2f}%"
            )
            await self.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
            with open(filename, 'rb') as f:
                await self.bot.send_document(chat_id=CHAT_ID, document=f)
        else:
            await self.bot.send_message(chat_id=CHAT_ID, text="⚠️ لم يتم العثور على صفقات في هذا النطاق.")

if __name__ == "__main__":
    asyncio.run(MidRangeBacktester().run())
