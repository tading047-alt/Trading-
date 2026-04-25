import ccxt
import pandas as pd
import numpy as np
import asyncio
from telegram import Bot
from datetime import datetime

# --- الإعدادات ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class ElitePortfolioEngine:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.initial_balance = 1000.0
        self.current_balance = 1000.0
        self.trade_amount = 100.0
        self.min_daily_volume = 15000000  # 15 مليون دولار كحد أدنى للسيولة
        self.blacklist = ['BTC/USDT', 'ETH/USDT', 'USDC/USDT', 'DAI/USDT', 'FDUSD/USDT', 'USDT/USDT']

    async def get_btc_status(self):
        """التحقق من صحة السوق عبر البيتكوين"""
        try:
            ohlcv = self.exchange.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=200)
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            ema200 = df['c'].ewm(span=200).mean().iloc[-1]
            # السوق آمن إذا كان BTC فوق EMA 200
            return df['c'].iloc[-1] > ema200, df['c'].pct_change(24).iloc[-1] * 100
        except: return False, 0

    def calculate_indicators(self, df):
        # حساب المؤشرات الأساسية
        df['ema200'] = df['c'].ewm(span=200).mean()
        df['sma20'] = df['c'].rolling(20).mean()
        df['std'] = df['c'].rolling(20).std()
        df['bw'] = (df['std'] * 4) / df['sma20']
        # RSI
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain/loss)))
        # ATR
        df['tr'] = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
        df['atr'] = df['tr'].rolling(14).mean()
        return df

    def get_elite_score(self, df, i, btc_24h_change):
        score = 0
        # 1. القوة النسبية (العملة أقوى من البيتكوين)
        coin_24h_change = (df['c'].iloc[i] - df['c'].iloc[max(0, i-24)]) / df['c'].iloc[max(0, i-24)] * 100
        if coin_24h_change > btc_24h_change: score += 20
        
        # 2. انضغاط البولنجر (Squeeze)
        if df['bw'].iloc[i] < df['bw'].iloc[max(0, i-100):i].min() * 1.15: score += 20
        
        # 3. الزخم الإيجابي (RSI)
        if 50 < df['rsi'].iloc[i] < 68: score += 20
        
        # 4. الاتجاه الصاعد (Above EMA 200)
        if df['c'].iloc[i] > df['ema200'].iloc[i]: score += 20
        
        # 5. دخول سيولة (Volume Spike)
        if df['v'].iloc[i] > df['v'].iloc[max(0, i-20):i].mean() * 2.5: score += 20
        
        return score

    async def backtest_symbol(self, symbol, btc_safe, btc_24h):
        if any(x in symbol for x in self.blacklist): return []
        try:
            # جلب البيانات
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=720)
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            
            # فلتر السيولة: استبعاد العملات الضعيفة برمجياً
            if (df['v'].iloc[-1] * df['c'].iloc[-1]) < self.min_daily_volume: return []
            
            df = self.calculate_indicators(df)
            trades = []
            
            for i in range(50, len(df) - 24):
                # شرط السكور 90 + شرط أمان البيتكوين
                if self.get_elite_score(df, i, btc_24h) >= 90 and btc_safe:
                    entry_p = df['c'].iloc[i]
                    tp = entry_p * 1.03
                    sl = entry_p * 0.97
                    
                    for j in range(i + 1, min(i + 48, len(df))):
                        if df['h'].iloc[j] >= tp:
                            trades.append({'time': df['t'].iloc[i], 'res': 'WIN', 'pnl': 3.0, 'sym': symbol})
                            i = j; break
                        if df['l'].iloc[j] <= sl:
                            trades.append({'time': df['t'].iloc[i], 'res': 'LOSS', 'pnl': -3.0, 'sym': symbol})
                            i = j; break
            return trades
        except: return []

    async def run_elite_simulation(self):
        await self.bot.send_message(chat_id=CHAT_ID, text="🏆 إطلاق محاكي 'النخبة' (Score 90+)...\n🛡️ تم تفعيل فلاتر البيتكوين والسيولة والقوة النسبية.")
        
        btc_safe, btc_24h = await self.get_btc_status()
        markets = self.exchange.load_markets()
        symbols = [s for s in markets if '/USDT' in s and markets[s]['active']][:800]
        
        all_trades = []
        for i in range(0, len(symbols), 50):
            batch = symbols[i:i+50]
            tasks = [self.backtest_symbol(sym, btc_safe, btc_24h) for sym in batch]
            results = await asyncio.gather(*tasks)
            for r in results: all_trades.extend(r)
            await asyncio.sleep(1)

        if all_trades:
            df_trades = pd.DataFrame(all_trades).sort_values(by='time')
            
            for _, trade in df_trades.iterrows():
                # محاكاة الربح بالدولار من الـ 100$
                self.current_balance += (self.trade_amount * (trade['pnl'] / 100))
            
            wins = len(df_trades[df_trades['res'] == 'WIN'])
            losses = len(df_trades[df_trades['res'] == 'LOSS'])
            win_rate = (wins / len(df_trades)) * 100
            
            filename = "Elite_90_Backtest.csv"
            df_trades.to_csv(filename, index=False)
            
            summary = (
                f"✅ **نتيجة محاكاة النخبة (Score 90):**\n\n"
                f"💰 الرصيد النهائي: {self.current_balance:.2f}$\n"
                f"📈 العائد الصافي: {((self.current_balance-1000)/1000)*100:.2f}%\n"
                f"🎯 عدد الصفقات: {len(df_trades)}\n"
                f"✅ ربح: {wins} | ❌ خسارة: {losses}\n"
                f"⚖️ نسبة النجاح: {win_rate:.2f}%"
            )
            await self.bot.send_message(chat_id=CHAT_ID, text=summary, parse_mode='Markdown')
            with open(filename, 'rb') as f:
                await self.bot.send_document(chat_id=CHAT_ID, document=f)
        else:
            await self.bot.send_message(chat_id=CHAT_ID, text="⚠️ لم يتم العثور على أي صفقات تحقق معايير النخبة (90+) في الشهر الماضي.")

if __name__ == "__main__":
    asyncio.run(ElitePortfolioEngine().run_elite_simulation())
