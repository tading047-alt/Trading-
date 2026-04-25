import ccxt
import pandas as pd
import numpy as np
import asyncio
from telegram import Bot
from datetime import datetime

# --- الإعدادات ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class PortfolioEngine:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.bot = Bot(token=TELEGRAM_TOKEN)
        # إعدادات المحفظة
        self.initial_wallet = 1000.0
        self.current_wallet = 1000.0
        self.position_size = 100.0  # دخول بـ 100$ لكل صفقة
        self.target_pct = 0.03      # ربح 3%
        self.stop_pct = 0.03        # خسارة 3%
        # قائمة الاستبعاد (العملات المستقرة والقيادية)
        self.blacklist = ['BTC/USDT', 'ETH/USDT', 'USDC/USDT', 'DAI/USDT', 'FDUSD/USDT', 'USDT/USDT']

    def apply_indicators(self, df):
        # حساب RSI و ATR و Bollinger Bands و EMA 200
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + (gain/loss)))
        df['atr'] = df['c'].rolling(14).std() # تبسيط للتذبذب
        df['ema200'] = df['c'].ewm(span=200).mean()
        df['sma20'] = df['c'].rolling(20).mean()
        df['std'] = df['c'].rolling(20).std()
        df['bw'] = (df['std'] * 4) / df['sma20']
        return df

    def get_score(self, df, i):
        score = 0
        if df['bw'].iloc[i] < df['bw'].iloc[max(0, i-50):i].min() * 1.1: score += 20 # Squeeze
        if df['c'].iloc[i] > df['ema200'].iloc[i]: score += 20                      # Trend
        if 50 < df['rsi'].iloc[i] < 70: score += 20                                # Momentum
        if df['v'].iloc[i] > df['v'].iloc[max(0, i-20):i].mean() * 2: score += 20    # Volume
        if df['h'].iloc[i-2] < df['l'].iloc[i]: score += 20                         # FVG
        return score

    async def test_symbol(self, symbol):
        if any(x in symbol for x in self.blacklist): return []
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=720) # شهر
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            df = self.apply_indicators(df)
            
            symbol_trades = []
            for i in range(50, len(df) - 24):
                if self.get_score(df, i) >= 80:
                    entry_p = df['c'].iloc[i]
                    tp = entry_p * (1 + self.target_pct)
                    sl = entry_p * (1 - self.stop_pct)
                    
                    for j in range(i + 1, min(i + 48, len(df))):
                        if df['h'].iloc[j] >= tp:
                            symbol_trades.append({'time': df['t'].iloc[i], 'res': 'WIN', 'pnl': self.position_size * 0.03, 'sym': symbol})
                            i = j; break
                        if df['l'].iloc[j] <= sl:
                            symbol_trades.append({'time': df['t'].iloc[i], 'res': 'LOSS', 'pnl': -self.position_size * 0.03, 'sym': symbol})
                            i = j; break
            return symbol_trades
        except: return []

    async def run_simulation(self):
        await self.bot.send_message(chat_id=CHAT_ID, text="📊 بدأت محاكاة المحفظة المحتملة...\n💰 رأس المال: 1000$ | الصفقة: 100$\n⏳ جاري فحص 800 عملة لمدة شهر...")
        
        markets = self.exchange.load_markets()
        symbols = [s for s in markets if '/USDT' in s and markets[s]['active']][:800]
        
        all_potential_trades = []
        for i in range(0, len(symbols), 50):
            batch = symbols[i:i+50]
            tasks = [self.test_symbol(sym) for sym in batch]
            results = await asyncio.gather(*tasks)
            for r in results: all_potential_trades.extend(r)
            await asyncio.sleep(1)

        if all_potential_trades:
            # ترتيب كافة الصفقات من جميع العملات حسب وقت حدوثها
            df_all = pd.DataFrame(all_potential_trades).sort_values(by='time')
            
            history = []
            for _, trade in df_all.iterrows():
                self.current_wallet += trade['pnl']
                history.append({
                    'Time': datetime.fromtimestamp(trade['time']/1000).strftime('%Y-%m-%d %H:%M'),
                    'Symbol': trade['sym'],
                    'Result': trade['res'],
                    'PnL_USD': trade['pnl'],
                    'Wallet_Balance': self.current_wallet
                })

            df_history = pd.DataFrame(history)
            df_history.to_csv("Portfolio_Backtest_Results.csv", index=False)
            
            total_profit_pct = ((self.current_wallet - self.initial_wallet) / self.initial_wallet) * 100
            summary = (
                f"🏁 **تقرير المحاكاة الشهرية النهائي:**\n\n"
                f"💵 الرصيد النهائي: {self.current_wallet:.2f}$\n"
                f"📈 العائد الإجمالي: {total_profit_pct:.2f}%\n"
                f"✅ عدد الصفقات الرابحة: {len(df_history[df_history['Result']=='WIN'])}\n"
                f"❌ عدد الصفقات الخاسرة: {len(df_history[df_history['Result']=='LOSS'])}\n"
                f"⚖️ نسبة النجاح: {(len(df_history[df_history['Result']=='WIN'])/len(df_history)*100):.2f}%"
            )
            await self.bot.send_message(chat_id=CHAT_ID, text=summary, parse_mode='Markdown')
            with open("Portfolio_Backtest_Results.csv", 'rb') as f:
                await self.bot.send_document(chat_id=CHAT_ID, document=f)

if __name__ == "__main__":
    asyncio.run(PortfolioEngine().run_simulation())
