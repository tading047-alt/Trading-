import ccxt
import pandas as pd
import numpy as np
import asyncio
import os
from datetime import timedelta
from telegram import Bot

# إعدادات
TELEGRAM_TOKEN = 'YOUR_TOKEN'
CHAT_ID = 'YOUR_CHAT_ID'

SLIPPAGE = 0.0005
COMMISSION = 0.001
RISK_PER_TRADE = 0.02
INITIAL_CAPITAL = 1000.0
ENTRY_SCORE = 88                  # عتبة عالية
SYMBOLS_LIMIT = 800
CANDLES_LIMIT = 4000
MAX_HOLD_CANDLES = 48
TP_ATR_MULT = 2.5
SL_ATR_MULT = 1.0
TRAIL_ACTIVATION = 1.5
ADX_THRESHOLD = 25

class SniperV25:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.bot = Bot(token=TELEGRAM_TOKEN)

    def add_indicators(self, df):
        # RSI 14
        delta = df['close'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        df['rsi'] = 100 - (100 / (1 + (gain.rolling(14).mean() / loss.rolling(14).mean())))

        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()

        # ATR
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()

        # Bollinger width
        df['sma20'] = df['close'].rolling(20).mean()
        df['std20'] = df['close'].rolling(20).std()
        df['bb_width'] = (df['std20'] * 4) / df['sma20']

        # ADX
        high_diff = df['high'].diff()
        low_diff = df['low'].diff()
        plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0.0)
        minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0.0)
        atr14 = tr.rolling(14).mean()
        plus_di = 100 * (pd.Series(plus_dm).rolling(14).mean() / atr14)
        minus_di = 100 * (pd.Series(minus_dm).rolling(14).mean() / atr14)
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
        df['adx'] = dx.rolling(14).mean()
        return df

    def get_score(self, df, i):
        # ADX إجباري
        if df['adx'].iloc[i] < ADX_THRESHOLD:
            return 0
        # EMA50 يجب أن يكون فوق EMA200 (اتجاه صاعد مؤكد)
        if df['ema50'].iloc[i] <= df['ema200'].iloc[i]:
            return 0
        # السعر فوق EMA200
        if df['close'].iloc[i] <= df['ema200'].iloc[i]:
            return 0

        score = 0
        # حجم تداول > 3x المتوسط
        vol_mean = df['volume'].iloc[max(0,i-20):i].mean()
        if vol_mean > 0 and df['volume'].iloc[i] > vol_mean * 3:
            score += 25
        # RSI بين 60 و 75
        if 60 < df['rsi'].iloc[i] < 75:
            score += 25
        # سعر فوق EMA200 (تأكيد إضافي)
        if df['close'].iloc[i] > df['ema200'].iloc[i]:
            score += 25
        # انفجار من ضيق بولينجر
        min_width = df['bb_width'].iloc[max(0,i-50):i].min()
        if min_width > 0 and df['bb_width'].iloc[i] < min_width * 1.3:
            score += 25
        return score

    def simulate_exit(self, df, entry_idx, entry_price, tp, sl, atr):
        trailing_active = False
        trailing_sl = sl
        for j in range(entry_idx+1, min(entry_idx+MAX_HOLD_CANDLES+1, len(df))):
            high, low = df['high'].iloc[j], df['low'].iloc[j]
            if not trailing_active:
                if high >= entry_price + atr * TRAIL_ACTIVATION:
                    trailing_active = True
                    trailing_sl = entry_price
            else:
                potential_sl = high - atr * SL_ATR_MULT
                if potential_sl > trailing_sl:
                    trailing_sl = potential_sl
            if low <= trailing_sl:
                return trailing_sl * (1 - SLIPPAGE), 'LOSS', j
            if high >= tp:
                return tp * (1 - SLIPPAGE), 'WIN', j
        last = min(entry_idx+MAX_HOLD_CANDLES, len(df)-1)
        return df['close'].iloc[last] * (1 - SLIPPAGE), 'TIME_EXIT', last

    async def backtest_symbol(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, '1h', limit=CANDLES_LIMIT)
            df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
            df.columns = ['timestamp','open','high','low','close','volume']
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = self.add_indicators(df)

            trades = []
            for i in range(200, len(df)-MAX_HOLD_CANDLES):
                score = self.get_score(df, i)
                if score < ENTRY_SCORE:
                    continue
                atr = df['atr'].iloc[i]
                if atr <= 0:
                    continue
                entry_close = df['close'].iloc[i]
                entry_price = entry_close * (1 + SLIPPAGE)
                tp = entry_close + atr * TP_ATR_MULT
                sl = entry_close - atr * SL_ATR_MULT
                exit_price, result, exit_idx = self.simulate_exit(df, i, entry_price, tp, sl, atr)
                gross = (exit_price / entry_price) - 1
                net = (gross - 2 * COMMISSION) * 100
                duration = (df['timestamp'].iloc[exit_idx] - df['timestamp'].iloc[i]).total_seconds() / 3600
                trades.append({
                    'symbol': symbol,
                    'entry_time': df['timestamp'].iloc[i],
                    'exit_time': df['timestamp'].iloc[exit_idx],
                    'duration_hours': round(duration, 2),
                    'entry_price': round(entry_price, 8),
                    'exit_price': round(exit_price, 8),
                    'result': result,
                    'pnl_pct': round(net, 4),
                    'score': score
                })
            return trades
        except:
            return []

    async def run(self):
        await self.bot.send_message(chat_id=CHAT_ID, text="🎯 V25: تشغيل القناص بمعايير مشددة...")
        markets = self.exchange.load_markets()
        symbols = [s for s in markets if '/USDT' in s and markets[s]['active']][:SYMBOLS_LIMIT]
        all_trades = []
        for i in range(0, len(symbols), 50):
            batch = symbols[i:i+50]
            tasks = [self.backtest_symbol(s) for s in batch]
            res = await asyncio.gather(*tasks)
            for r in res: all_trades.extend(r)

        if not all_trades:
            await self.bot.send_message(chat_id=CHAT_ID, text="⚠️ لا توجد صفقات")
            return

        # حساب تراكمي
        wallet = INITIAL_CAPITAL
        for t in all_trades:
            wallet *= (1 + t['pnl_pct']/100)
        profit = wallet - INITIAL_CAPITAL

        wins = [t for t in all_trades if t['result']=='WIN']
        losses = [t for t in all_trades if t['result']=='LOSS']
        exits = [t for t in all_trades if t['result']=='TIME_EXIT']
        avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
        avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
        avg_dur = np.mean([t['duration_hours'] for t in all_trades])

        text = (
            f"📊 V25 نتائج:\n"
            f"💰 النهائي: {wallet:.2f}$ (الربح: {profit:.2f}$)\n"
            f"📈 العائد: {(wallet/INITIAL_CAPITAL -1)*100:.2f}%\n"
            f"🎯 الصفقات: {len(all_trades)}\n"
            f"🏆 النجاح: {len(wins)/len(all_trades)*100:.2f}% ({len(wins)})\n"
            f"❌ خسائر: {len(losses)} | ⏳ زمنية: {len(exits)}\n"
            f"📊 متوسط ربح: {avg_win:.2f}% / خسارة: {avg_loss:.2f}%\n"
            f"⏱️ مدة: {avg_dur:.1f} ساعة"
        )
        await self.bot.send_message(chat_id=CHAT_ID, text=text)

        # CSV
        csv_file = 'v25_trades.csv'
        df_csv = pd.DataFrame(all_trades)
        df_csv.to_csv(csv_file, index=False)
        with open(csv_file, 'rb') as f:
            await self.bot.send_document(chat_id=CHAT_ID, document=f, filename=csv_file,
                                         caption="تقرير V25 التفصيلي")
        os.remove(csv_file)

if __name__ == '__main__':
    asyncio.run(SniperV25().run())
