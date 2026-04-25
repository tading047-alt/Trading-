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
    params = (
        ('stop_loss', 0.02),    # 2% وقف خسارة
        ('take_profit', 0.04),  # 4% جني أرباح
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20, devfactor=2)
        self.keltner = bt.indicators.ATR(self.data, period=20)
        self.sma = bt.indicators.SMA(self.data.close, period=20)
        
        self.entry_date = None
        self.entry_price = None
        self.exit_price = None
        self.trade_status = "No_Trade" # لتوضيح هل ربحت أم خسرت

    def notify_order(self, order):
        if order.status in [order.Completed] and order.isbuy():
            # تسجيل بيانات الدخول عند اكتمال أمر الشراء
            self.entry_date = bt.num2date(order.executed.dt)
            self.entry_price = order.executed.price
            self.trade_status = "Open"

    def next(self):
        if not self.position:
            # شرط الدخول: اختراق الحد العلوي للبولنجر
            if self.data.close[0] > self.bb.top[0]:
                self.buy()
        else:
            # حساب مستويات الأهداف بناءً على سعر الدخول
            sl_price = self.entry_price * (1.0 - self.p.stop_loss)
            tp_price = self.entry_price * (1.0 + self.p.take_profit)

            # التحقق من ملامسة الأهداف (نختبر السعر الأدنى والأعلى للشمعة الحالية)
            if self.data.low[0] <= sl_price:
                self.close()
                self.exit_price = sl_price
                self.trade_status = "Loss (-2%)"
            elif self.data.high[0] >= tp_price:
                self.close()
                self.exit_price = tp_price
                self.trade_status = "Win (+4%)"
            # شرط خروج إضافي (اختياري): إذا كسر السعر المتوسط المتحرك قبل الأهداف
            elif self.data.close[0] < self.sma[0]:
                self.close()
                self.exit_price = self.data.close[0]
                self.trade_status = "Closed_by_SMA"

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
            
            cerebro = bt.Cerebro()
            cerebro.addstrategy(SqueezeStrategy)
            data = bt.feeds.PandasData(dataname=df.assign(datetime=pd.to_datetime(df['datetime'], unit='ms')).set_index('datetime'))
            cerebro.adddata(data)
            cerebro.broker.setcash(1000.0)
            cerebro.broker.setcommission(commission=0.001) # رسوم 0.1%

            results = cerebro.run()
            strat = results[0]
            profit = round(((cerebro.broker.getvalue() - 1000) / 1000) * 100, 2)

            return {
                'Symbol': symbol,
                'Current_Price': current_price,
                'Date_Entree': strat.entry_date.strftime('%Y-%m-%d') if strat.entry_date else "No_Breakout",
                'Heure_Entree': strat.entry_date.strftime('%H:%M') if strat.entry_date else "--:--",
                'Prix_Entree': round(strat.entry_price, 6) if strat.entry_price else 0,
                'Prix_Sortie': round(strat.exit_price, 6) if strat.exit_price else 0,
                'Status_Trade': strat.trade_status,
                'Resultat_Net_%': profit
            }
        except Exception:
            return None

async def send_to_telegram(all_data):
    file_path = "Detailed_Report_SL_TP.csv"
    df = pd.DataFrame(all_data)
    # ترتيب العملات التي حققت صفقات أولاً
    df = df.sort_values(by='Resultat_Net_%', ascending=False)
    df.to_csv(file_path, index=False)

    wins = len(df[df['Status_Trade'] == "Win (+4%)"])
    losses = len(df[df['Status_Trade'] == "Loss (-2%)"])

    summary = f"🚀 تقرير الباكتيست (SL 2% / TP 4%)\n"
    summary += f"📊 إجمالي العملات الممسوحة: {len(df)}\n"
    summary += f"✅ صفقات رابحة: {wins}\n"
    summary += f"❌ صفقات خاسرة: {losses}\n"
    summary += f"🔝 أفضل ربح محقق: {df['Resultat_Net_%'].max()}%\n"

    bot = Bot(token=TELEGRAM_TOKEN)
    async with bot:
        await bot.send_message(chat_id=CHAT_ID, text=summary)
        with open(file_path, 'rb') as f:
            await bot.send_document(chat_id=CHAT_ID, document=f, caption="التقرير التفصيلي لنتائج الصفقات 📄")

async def main():
    scanner = CryptoScanner()
    tickers = scanner.exchange.fetch_tickers()
    symbols = [s[0] for s in sorted(tickers.items(), key=lambda x: x[1].get('quoteVolume', 0), reverse=True) if '/USDT' in s[0]][:300]
    
    results_list = []
    for i, symbol in enumerate(symbols):
        print(f"[{i+1}/300] Testing {symbol}...")
        res = scanner.run_backtest(symbol)
        if res: results_list.append(res)
    
    await send_to_telegram(results_list)

if __name__ == "__main__":
    asyncio.run(main())
