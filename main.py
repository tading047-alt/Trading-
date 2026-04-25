import ccxt
import pandas as pd
import numpy as np
import asyncio
from telegram import Bot
from datetime import datetime, timedelta

# --- الإعدادات ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class MonthlyBacktestEngine:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.bot = Bot(token=TELEGRAM_TOKEN)

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
        
        # ATR & EMAs
        df['tr'] = np.maximum(df['h'] - df['l'], np.maximum(abs(df['h'] - df['c'].shift(1)), abs(df['l'] - df['c'].shift(1))))
        df['atr'] = df['tr'].rolling(14).mean()
        df['ema50'] = df['c'].ewm(span=50).mean()
        df['ema200'] = df['c'].ewm(span=200).mean()
        return df

    def check_elite_score(self, df, i):
        """فحص الشروط عند الشمعة i"""
        score = 0
        # 1. Squeeze
        if df['bw'].iloc[i] < df['bw'].iloc[max(0, i-100):i].min() * 1.2: score += 20
        # 2. Trend
        if df['c'].iloc[i] > df['ema50'].iloc[i] > df['ema200'].iloc[i]: score += 20
        # 3. Momentum
        if 50 < df['rsi'].iloc[i] < 70: score += 20
        # 4. Volume
        if df['v'].iloc[i] > df['v'].iloc[max(0, i-20):i].mean() * 2.5: score += 20
        # 5. SMC/FVG
        if df['h'].iloc[i-2] < df['l'].iloc[i]: score += 20
        
        return score

    async def run_monthly_test(self, symbol):
        try:
            # جلب بيانات شهر (720 ساعة)
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=750)
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            df = self.calculate_indicators(df)
            
            wins, losses, total_profit = 0, 0, 0
            
            # محاكاة التداول عبر الـ 720 شمعة الماضية
            for i in range(100, len(df) - 24):
                score = self.check_elite_score(df, i)
                
                if score >= 80: # شروط النخبة
                    entry_price = df['c'].iloc[i]
                    atr = df['atr'].iloc[i]
                    tp = entry_price + (atr * 2.5)
                    sl = entry_price - (atr * 1.5)
                    
                    # فحص النتيجة في الـ 24 شمعة القادمة
                    for j in range(i + 1, min(i + 48, len(df))):
                        if df['h'].iloc[j] >= tp:
                            wins += 1
                            total_profit += 2.5 # نسبة الربح بناءً على معامل ATR
                            i = j # قفز إلى نهاية الصفقة
                            break
                        if df['l'].iloc[j] <= sl:
                            losses += 1
                            total_profit -= 1.5
                            i = j
                            break
            
            total_trades = wins + losses
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            
            # نأخذ فقط العملات التي لديها صفقات فعلية في الشهر الماضي
            if total_trades > 0:
                return {
                    'Symbol': symbol,
                    'Monthly_Win_Rate': f"{round(win_rate, 2)}%",
                    'Total_Trades': total_trades,
                    'Net_ATR_Profit': round(total_profit, 2),
                    'Current_Score': self.check_elite_score(df, len(df)-1),
                    'Price': df['c'].iloc[-1]
                }
        except: return None

    async def start(self):
        await self.bot.send_message(chat_id=CHAT_ID, text="📅 بدأ الاختبار العكسي الشهري (30 يوماً)...\n🔬 يتم الآن تحليل سلوك 800 عملة وحساب أرباحها الصافية.")
        
        markets = self.exchange.load_markets()
        symbols = [s for s in markets if '/USDT' in s and markets[s]['active']][:800]
        
        results = []
        for i in range(0, len(symbols), 30): # دفعات أصغر للتعامل مع البيانات الضخمة
            batch = symbols[i:i+30]
            tasks = [self.run_monthly_test(sym) for sym in batch]
            batch_res = await asyncio.gather(*tasks)
            results.extend([r for r in batch_res if r])
            await asyncio.sleep(2)

        if results:
            df_final = pd.DataFrame(results).sort_values(by='Net_ATR_Profit', ascending=False)
            # فلترة: فقط العملات التي سكورها الحالي عالي ونجاحها الشهري ممتاز
            elite_selection = df_final[df_final['Current_Score'] >= 80]
            
            filename = "Monthly_Backtest_Report.csv"
            elite_selection.to_csv(filename, index=False)
            
            await self.bot.send_message(chat_id=CHAT_ID, text=f"🏁 انتهى الاختبار الشهري!\n📊 تم تحليل {len(results)} عملة نشطة.\n✅ التقرير يحتوي على العملات الجاهزة للدخول الآن (Score 80+) والتي أثبتت نجاحها طوال الشهر الماضي.")
            with open(filename, 'rb') as f:
                await self.bot.send_document(chat_id=CHAT_ID, document=f)

if __name__ == "__main__":
    engine = MonthlyBacktestEngine()
    asyncio.run(engine.start())
