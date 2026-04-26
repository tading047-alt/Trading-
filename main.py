import ccxt
import pandas as pd
import numpy as np
import asyncio
from telegram import Bot
from datetime import datetime

# --- الإعدادات ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class ProfessionalPortfolioEngine:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.wallet = 1000.0  # رأس المال الابتدائي
        self.trade_amount = 100.0
        self.min_volume = 15000000  # فلتر السيولة (15 مليون$)
        self.blacklist = ['BTC/USDT', 'ETH/USDT', 'USDC/USDT', 'DAI/USDT', 'FDUSD/USDT', 'USDT/USDT']

    async def get_market_condition(self):
        """فحص اتجاه البيتكوين العام"""
        try:
            ohlcv = self.exchange.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=200)
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            ema200 = df['c'].ewm(span=200).mean().iloc[-1]
            return df['c'].iloc[-1] > ema200 # True إذا كان السوق صاعداً
        except: return False

    def calculate_indicators(self, df):
        # RSI
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain/loss)))
        # EMA & Bollinger
        df['ema200'] = df['c'].ewm(span=200).mean()
        df['sma20'] = df['c'].rolling(20).mean()
        df['std'] = df['c'].rolling(20).std()
        df['bw'] = (df['std'] * 4) / df['sma20']
        # ATR لتقدير التذبذب
        df['tr'] = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
        df['atr'] = df['tr'].rolling(14).mean()
        return df

    def get_elite_score(self, df, i):
        score = 0
        # 1. Squeeze Check
        if df['bw'].iloc[i] < df['bw'].iloc[max(0, i-50):i].min() * 1.1: score += 20
        # 2. Institutional Trend
        if df['c'].iloc[i] > df['ema200'].iloc[i]: score += 20
        # 3. Momentum RSI
        if 50 < df['rsi'].iloc[i] < 65: score += 20
        # 4. Whale Volume
        if df['v'].iloc[i] > df['v'].iloc[max(0, i-20):i].mean() * 2.2: score += 20
        # 5. Smart Money FVG
        if df['h'].iloc[i-2] < df['l'].iloc[i]: score += 20
        return score

    async def backtest_symbol(self, symbol, market_safe):
        if any(x in symbol for x in self.blacklist): return []
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=740)
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            
            # فلتر السيولة الصارم
            if (df['v'].iloc[-1] * df['c'].iloc[-1]) < self.min_volume: return []
            
            df = self.calculate_indicators(df)
            trades = []
            
            for i in range(50, len(df) - 24):
                # الدخول فقط بسكور 90 وتحت حماية البيتكوين
                if self.get_elite_score(df, i) >= 90 and market_safe:
                    entry_p = df['c'].iloc[i]
                    tp = entry_p * 1.04 # هدف 4%
                    sl = entry_p * 0.98 # وقف 2% (R:R 2:1)
                    
                    for j in range(i + 1, min(i + 48, len(df))):
                        if df['h'].iloc[j] >= tp:
                            trades.append({'time': df['t'].iloc[i], 'res': 'WIN', 'pnl_usd': 4.0, 'sym': symbol})
                            i = j; break
                        if df['l'].iloc[j] <= sl:
                            trades.append({'time': df['t'].iloc[i], 'res': 'LOSS', 'pnl_usd': -2.0, 'sym': symbol})
                            i = j; break
            return trades
        except: return []

    async def run_alpha_simulation(self):
        await self.bot.send_message(chat_id=CHAT_ID, text="🚀 إطلاق محاكي 'ألفا المهني'...\n💎 سكور 90 | هدف 4% | وقف 2% | فلتر BTC & سيولة.")
        
        market_safe = await self.get_market_condition()
        markets = self.exchange.load_markets()
        symbols = [s for s in markets if '/USDT' in s and markets[s]['active']][:800]
        
        results = []
        for i in range(0, len(symbols), 50):
            batch = symbols[i:i+50]
            tasks = [self.backtest_symbol(sym, market_safe) for sym in batch]
            res = await asyncio.gather(*tasks)
            for r in res: results.extend(r)
            await asyncio.sleep(1)

        if results:
            df_trades = pd.DataFrame(results).sort_values(by='time')
            for _, t in df_trades.iterrows():
                self.wallet += t['pnl_usd'] # محاكاة الربح/الخسارة الفعلي من الـ 100$

            wins = len(df_trades[df_trades['res'] == 'WIN'])
            losses = len(df_trades[df_trades['res'] == 'LOSS'])
            win_rate = (wins / len(df_trades)) * 100
            
            filename = "Alpha_Elite_Report.csv"
            df_trades.to_csv(filename, index=False)
            
            summary = (
                f"🏆 **نتائج نظام ألفا المطور (شهر كامل):**\n\n"
                f"💰 الرصيد النهائي: {self.wallet:.2f}$\n"
                f"📈 العائد الصافي: {((self.wallet-1000)/1000)*100:.2f}%\n"
                f"🎯 عدد صفقات النخبة: {len(df_trades)}\n"
                f"✅ WIN: {wins} | ❌ LOSS: {losses}\n"
                f"⚖️ نسبة النجاح المتوقعة: {win_rate:.2f}%\n\n"
                f"💡 ملاحظة: عدد الصفقات قلّ لأن الجودة ارتفعت."
            )
            await self.bot.send_message(chat_id=CHAT_ID, text=summary, parse_mode='Markdown')
            with open(filename, 'rb') as f:
                await self.bot.send_document(chat_id=CHAT_ID, document=f)

if __name__ == "__main__":
    asyncio.run(ProfessionalPortfolioEngine().run_alpha_simulation())
