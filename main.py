import ccxt
import pandas as pd
import backtrader as bt
import asyncio
import os
from telegram import Bot
from datetime import datetime, timedelta

# --- الإعدادات الخاصة بك ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class SqueezeStrategy(bt.Strategy):
    def __init__(self):
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20, devfactor=2)
        self.keltner = bt.indicators.ATR(self.data, period=20)
        self.sma = bt.indicators.SMA(self.data.close, period=20)
        
        # تخزين بيانات الدخول
        self.entry_date = None
        self.entry_price = None

    def notify_order(self, order):
        if order.status in [order.Completed] and order.isbuy():
            self.entry_date = bt.num2date(order.executed.dt)
            self.entry_price = order.executed.price

    def next(self):
        bb_width = self.bb.top[0] - self.bb.bot[0]
        # إذا اخترق السعر حدود بولينجر، نعتبره دخولاً للتقرير حتى لو لم يكن ضغطاً مثالياً
        if not self.position:
            if self.data.close[0] > self.bb.top[0]:
                self.buy()
        elif self.data.close[0] < self.sma[0]:
            self.close()

class CryptoScanner:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})

    def run_backtest(self, symbol):
        try:
            since = self.exchange.parse8601((datetime.now() - timedelta(days=30)).isoformat())
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', since=since)
            if not ohlcv: return None

            df = pd.DataFrame(ohlcv, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
            current_price = df['close'].iloc[-1]
            avg_vol = df['volume'].mean()

            cerebro = bt.Cerebro()
            cerebro.addstrategy(SqueezeStrategy)
            data = bt.feeds.PandasData(dataname=df.assign(datetime=pd.to_datetime(df['datetime'], unit='ms')).set_index('datetime'))
            cerebro.adddata(data)
            cerebro.broker.setcash(1000.0)
            
            results = cerebro.run()
            strat = results[0]
            profit = round(((cerebro.broker.getvalue() - 1000) / 1000) * 100, 2)

            # ضمان وجود بيانات في كل سطر
            return {
                'Symbol': symbol,
                'Current_Price': current_price,
                'Avg_Volume': round(avg_vol, 2),
                'Date_Entree': strat.entry_date.strftime('%Y-%m-%d') if strat.entry_date else "No_Breakout",
                'Heure_Entree': strat.entry_date.strftime('%H:%M') if strat.entry_date else "--:--",
                'Prix_Entree': round(strat.entry_price, 6) if strat.entry_price else 0,
                'Resultat_Net_%': profit
            }
        except Exception:
            return None

async def send_to_telegram(all_data):
    file_path = "Detailed_Report.csv"
    df = pd.DataFrame(all_data).sort_values(by='Resultat_Net_%', ascending=False)
    df.to_csv(file_path, index=False)

    summary = f"✅ فحص شامل لـ {len(df)} عملة\n"
    summary += f"📅 تاريخ التقرير: {datetime.now().strftime('%Y-%m-%d')}\n"
    summary += f"🔝 أفضل ربح محقق: {df['Resultat_Net_%'].max()}%"

    bot = Bot(token=TELEGRAM_TOKEN)
    async with bot:
        await bot.send_message(chat_id=CHAT_ID, text=summary)
        with open(file_path, 'rb') as f:
            await bot.send_document(chat_id=CHAT_ID, document=f, caption="التقرير الكامل بجميع المعطيات المتاحة 📄")

async def main():
    scanner = CryptoScanner()
    tickers = scanner.exchange.fetch_tickers()
    symbols = [s[0] for s in sorted(tickers.items(), key=lambda x: x[1].get('quoteVolume', 0), reverse=True) if '/USDT' in s[0]][:300]
    
    results_list = []
    for i, symbol in enumerate(symbols):
        print(f"[{i+1}/300] Analyzing {symbol}...")
        res = scanner.run_backtest(symbol)
        if res: results_list.append(res)
    
    await send_to_telegram(results_list)

if __name__ == "__main__":
    asyncio.run(main())
