import ccxt
import pandas as pd
import backtrader as bt
import asyncio
from telegram import Bot
from datetime import datetime, timedelta

# --- Configuration ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

class InstitutionalScoreStrategy(bt.Strategy):
    params = (
        ('sl', 0.02), # Stop Loss 2%
        ('tp', 0.04), # Take Profit 4%
        ('min_score', 65), # Score minimum pour entrer
    )

    def __init__(self):
        # 1. Moyennes Mobiles exponentielles (9, 21, 50, 200)
        self.ema9 = bt.indicators.EMA(period=9)
        self.ema21 = bt.indicators.EMA(period=21)
        self.ema50 = bt.indicators.EMA(period=50)
        self.ema200 = bt.indicators.EMA(period=200)
        
        # 2. RSI et MACD
        self.rsi = bt.indicators.RSI(period=14)
        self.macd = bt.indicators.MACD(period_me1=12, period_me2=26, period_signal=9)
        
        # 3. Bollinger et Volume
        self.bb = bt.indicators.BollingerBands(period=20)
        self.atr = bt.indicators.ATR(period=20)
        self.vol_sma = bt.indicators.SMA(self.data.volume, period=20)

        # Variables de suivi pour le CSV
        self.trade_results = {
            'score': 0,
            'details': "",
            'status': "No Trade",
            'entry_price': 0,
            'exit_price': 0
        }

    def get_detailed_score(self):
        score = 0
        reasons = []

        # Analyse des EMAs (Alignement haussier)
        if self.ema9[0] > self.ema21[0] > self.ema50[0] > self.ema200[0]:
            score += 30
            reasons.append("EMA_Alignment")

        # Bollinger Squeeze (Compression)
        if (self.bb.top[0] - self.bb.bot[0]) < (self.atr[0] * 1.5):
            score += 20
            reasons.append("BB_Squeeze")

        # Volume Whale (Pic de volume)
        if self.data.volume[0] > self.vol_sma[0] * 2.5:
            score += 20
            reasons.append("Whale_Volume")

        # RSI Momentum (Zone de force)
        if 50 < self.rsi[0] < 70:
            score += 15
            reasons.append("RSI_Strong")

        # MACD Bullish (Croisement positif)
        if self.macd.macd[0] > self.macd.signal[0]:
            score += 15
            reasons.append("MACD_Bullish")

        return score, "|".join(reasons)

    def next(self):
        if not self.position:
            s, d = self.get_detailed_score()
            if s >= self.p.min_score:
                self.buy()
                self.trade_results['score'] = s
                self.trade_results['details'] = d
                self.trade_results['entry_price'] = self.data.close[0]
                self.sl_price = self.data.close[0] * (1 - self.p.sl)
                self.tp_price = self.data.close[0] * (1 + self.p.tp)
        else:
            if self.data.low[0] <= self.sl_price:
                self.close()
                self.trade_results['status'] = "Loss (-2%)"
                self.trade_results['exit_price'] = self.sl_price
            elif self.data.high[0] >= self.tp_price:
                self.close()
                self.trade_results['status'] = "Win (+4%)"
                self.trade_results['exit_price'] = self.tp_price

class BacktestProcessor:
    def __init__(self):
        self.exchange = ccxt.binance()

    def run(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=500)
            df = pd.DataFrame(ohlcv, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['datetime'], unit='ms')
            
            cerebro = bt.Cerebro()
            cerebro.addstrategy(InstitutionalScoreStrategy)
            data = bt.feeds.PandasData(dataname=df.set_index('datetime'))
            cerebro.adddata(data)
            cerebro.broker.setcash(1000.0)
            
            results = cerebro.run()
            res = results[0].trade_results
            res['Symbol'] = symbol
            res['Final_Value'] = round(cerebro.broker.getvalue(), 2)
            return res
        except:
            return None

async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text="🚀 Lancement du Backtest Multi-Score (300 paires)...")
    
    processor = BacktestProcessor()
    tickers = processor.exchange.fetch_tickers()
    symbols = [s[0] for s in sorted(tickers.items(), key=lambda x: x[1].get('quoteVolume', 0), reverse=True) if '/USDT' in s[0]][:300]
    
    final_results = []
    for i, sym in enumerate(symbols):
        print(f"[{i+1}/300] Analyse de {sym}...")
        report = processor.run(sym)
        if report:
            final_results.append(report)
    
    # Création du CSV avec les colonnes Score
    df = pd.DataFrame(final_results)
    # On trie par Score décroissant pour voir les meilleures opportunités en haut
    df = df.sort_values(by='score', ascending=False)
    
    filename = "Backtest_Score_Report.csv"
    df.to_csv(filename, index=False)
    
    # Résumé Telegram
    win_count = len(df[df['status'] == "Win (+4%)"])
    loss_count = len(df[df['status'] == "Loss (-2%)"])
    
    msg = f"📊 **Rapport de Score terminé**\n\n"
    msg += f"✅ Trades Gagnants (+4%): {win_count}\n"
    msg += f"❌ Trades Perdants (-2%): {loss_count}\n"
    msg += f"🔥 Meilleur Score trouvé: {df['score'].max()}/100"
    
    await bot.send_message(chat_id=CHAT_ID, text=msg)
    with open(filename, 'rb') as f:
        await bot.send_document(chat_id=CHAT_ID, document=f, caption="Détails complets avec Scores et Indicateurs 📄")

if __name__ == "__main__":
    asyncio.run(main())
