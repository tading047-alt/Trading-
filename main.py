import ccxt
import pandas as pd
import numpy as np
import asyncio
import os
from telegram import Bot

# ==================== إعدادات ====================
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

SLIPPAGE = 0.0005
COMMISSION = 0.001
RISK_PER_TRADE = 0.02
INITIAL_CAPITAL = 1000.0
ENTRY_SCORE = 85                # عتبة عالية لكن بدون شروط إجبارية
SYMBOLS_LIMIT = 800
CANDLES_LIMIT = 4000
MAX_HOLD_CANDLES = 48
TP_ATR_MULT = 2.5
INITIAL_SL_ATR = 0.5
TRAIL_ACTIVATION = 0.7
TRAIL_SL_ATR = 1.0

EXCLUDED_ASSETS = {'BTC', 'ETH'}
STABLECOINS = {'USDC', 'BUSD', 'USDP', 'TUSD', 'DAI', 'USDD', 'FDUSD', 'USTC'}

class SniperV27:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.bot = Bot(token=TELEGRAM_TOKEN)

    def filter_symbols(self, all_symbols):
        filtered = []
        for sym in all_symbols:
            if not sym.endswith('/USDT'): continue
            base = sym.replace('/USDT', '')
            if base in STABLECOINS or base in EXCLUDED_ASSETS: continue
            if base.endswith(('DOWN', 'UP', 'BULL', 'BEAR')): continue
            if len(base) > 10: continue
            filtered.append(sym)
        return filtered

    def add_indicators(self, df):
        # RSI 14
        delta = df['close'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        df['rsi'] = 100 - (100 / (1 + (gain.rolling(14).mean() / loss.rolling(14).mean())))

        # EMAs
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

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

        # حجم
        df['vol_sma20'] = df['volume'].rolling(20).mean()
        df['vol_ratio'] = df['volume'] / df['vol_sma20']
        df['vol_max50'] = df['volume'].rolling(50).max()

        # MACD
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd_line'] = ema12 - ema26
        df['macd_signal'] = df['macd_line'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd_line'] - df['macd_signal']

        # قوة الشمعة
        df['body'] = abs(df['close'] - df['open'])
        df['candle_range'] = df['high'] - df['low']
        df['body_ratio'] = df['body'] / df['candle_range'].replace(0, np.nan)
        return df

    def get_score(self, df, i):
        """
        نظام نقاط بحت من 0 إلى 100. لا شروط إجبارية.
        """
        score = 0

        # 1. ADX قوي ومتزايد (حتى 20 نقطة)
        if df['adx'].iloc[i] > 30:
            score += 15
        elif df['adx'].iloc[i] > 25:
            score += 10
        elif df['adx'].iloc[i] > 20:
            score += 5
        if i >= 3 and df['adx'].iloc[i] > df['adx'].iloc[i-3]:
            score += 5

        # 2. ترتيب المتوسطات (حتى 15 نقطة)
        if df['ema20'].iloc[i] > df['ema50'].iloc[i]:
            score += 5
        if df['ema50'].iloc[i] > df['ema200'].iloc[i]:
            score += 5
        if df['ema20'].iloc[i] > df['ema50'].iloc[i] > df['ema200'].iloc[i]:
            score += 5  # مكافأة إضافية للترتيب المثالي

        # 3. حجم تداول استثنائي (حتى 25 نقطة)
        if df['vol_ratio'].iloc[i] > 4.0:
            score += 25
        elif df['vol_ratio'].iloc[i] > 3.0:
            score += 20
        elif df['vol_ratio'].iloc[i] > 2.0:
            score += 15
        elif df['vol_ratio'].iloc[i] > 1.5:
            score += 5

        # 4. RSI زخم (حتى 15 نقطة)
        if 55 < df['rsi'].iloc[i] < 75:
            score += 15
        elif 50 < df['rsi'].iloc[i] < 80:
            score += 8

        # 5. ضيق بولينجر (حتى 15 نقطة)
        min_width_50 = df['bb_width'].iloc[max(0, i-50):i].min()
        if min_width_50 > 0:
            ratio = df['bb_width'].iloc[i] / min_width_50
            if ratio < 1.1:
                score += 15
            elif ratio < 1.2:
                score += 10
            elif ratio < 1.3:
                score += 5

        # 6. شمعة صاعدة قوية (حتى 15 نقطة)
        if df['close'].iloc[i] > df['open'].iloc[i]:
            candle_score = 0
            if df['body_ratio'].iloc[i] > 0.7:
                candle_score += 10
            if df['close'].iloc[i] >= df['high'].iloc[i] * 0.99:
                candle_score += 5
            score += candle_score

        # 7. MACD تأكيد (حتى 10 نقاط)
        if df['macd_line'].iloc[i] > 0:
            score += 3
        if df['macd_line'].iloc[i] > df['macd_signal'].iloc[i]:
            score += 4
        if df['macd_hist'].iloc[i] > 0:
            score += 3

        # 8. تأكيد شمعة تالية (حتى 15 نقطة - يفحص خارجياً)
        # سنضيف هذا لاحقاً في منطق الدخول

        return min(score, 100)

    def simulate_exit(self, df, entry_idx, entry_price, tp, atr):
        initial_sl = entry_price - (atr * INITIAL_SL_ATR)
        trailing_active = False
        trailing_sl = initial_sl

        for j in range(entry_idx + 1, min(entry_idx + MAX_HOLD_CANDLES + 1, len(df))):
            high, low = df['high'].iloc[j], df['low'].iloc[j]

            if not trailing_active:
                if high >= entry_price + atr * TRAIL_ACTIVATION:
                    trailing_active = True
                    trailing_sl = entry_price
            else:
                potential_sl = high - atr * TRAIL_SL_ATR
                if potential_sl > trailing_sl:
                    trailing_sl = potential_sl

            if low <= trailing_sl:
                return trailing_sl * (1 - SLIPPAGE), 'LOSS', j
            if high >= tp:
                return tp * (1 - SLIPPAGE), 'WIN', j

        last_idx = min(entry_idx + MAX_HOLD_CANDLES, len(df) - 1)
        return df['close'].iloc[last_idx] * (1 - SLIPPAGE), 'TIME_EXIT', last_idx

    async def backtest_symbol(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, '1h', limit=CANDLES_LIMIT)
            df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
            df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = self.add_indicators(df)

            trades = []
            for i in range(200, len(df) - MAX_HOLD_CANDLES - 1):
                score = self.get_score(df, i)
                
                # تأكيد شمعة تالية يضيف نقاط
                if i+1 < len(df):
                    if df['high'].iloc[i+1] > df['high'].iloc[i]:
                        score += 15  # تأكيد الاختراق
                    if df['close'].iloc[i+1] > df['close'].iloc[i]:
                        score += 5   # تأكيد إضافي

                if score < ENTRY_SCORE:
                    continue

                atr = df['atr'].iloc[i]
                if atr <= 0: continue

                entry_price = df['open'].iloc[i+1] * (1 + SLIPPAGE)
                tp = entry_price + (atr * TP_ATR_MULT)

                exit_price, result, exit_idx = self.simulate_exit(df, i+1, entry_price, tp, atr)
                gross = (exit_price / entry_price) - 1
                net = (gross - 2 * COMMISSION) * 100
                duration = (df['timestamp'].iloc[exit_idx] - df['timestamp'].iloc[i+1]).total_seconds() / 3600

                trades.append({
                    'symbol': symbol,
                    'entry_time': df['timestamp'].iloc[i+1],
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
        await self.bot.send_message(chat_id=CHAT_ID, text="🎯 V27: سكور مرن (0-100) بعتبة 85...")

        markets = self.exchange.load_markets()
        all_symbols = [s for s in markets if markets[s]['active']]
        symbols = self.filter_symbols(all_symbols)[:SYMBOLS_LIMIT]

        await self.bot.send_message(chat_id=CHAT_ID, text=f"🔍 فحص {len(symbols)} عملة...")

        all_trades = []
        for i in range(0, len(symbols), 50):
            batch = symbols[i:i+50]
            tasks = [self.backtest_symbol(s) for s in batch]
            res = await asyncio.gather(*tasks)
            for r in res: all_trades.extend(r)

        if not all_trades:
            await self.bot.send_message(chat_id=CHAT_ID, text="⚠️ لا توجد صفقات.")
            return

        wallet = INITIAL_CAPITAL
        for t in all_trades:
            wallet *= (1 + t['pnl_pct'] / 100)

        wins = [t for t in all_trades if t['result'] == 'WIN']
        losses = [t for t in all_trades if t['result'] == 'LOSS']
        exits = [t for t in all_trades if t['result'] == 'TIME_EXIT']
        avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
        avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
        avg_dur = np.mean([t['duration_hours'] for t in all_trades])

        total_wins = sum(t['pnl_pct'] for t in wins)
        total_losses = abs(sum(t['pnl_pct'] for t in losses))
        profit_factor = total_wins / total_losses if total_losses else float('inf')

        text = (
            f"📊 *V27 - سكور مرن:*\n\n"
            f"💰 النهائي: {wallet:.2f}$ ({((wallet/INITIAL_CAPITAL)-1)*100:.2f}%)\n"
            f"🎯 الصفقات: {len(all_trades)}\n"
            f"🏆 نجاح: {(len(wins)/len(all_trades)*100):.2f}% ({len(wins)})\n"
            f"❌ خسائر: {len(losses)} | ⏳ زمنية: {len(exits)}\n"
            f"📊 متوسط ربح: {avg_win:.2f}% | خسارة: {avg_loss:.2f}%\n"
            f"📐 عامل الربح: {profit_factor:.2f}\n"
            f"⏱️ متوسط المدة: {avg_dur:.1f}h"
        )
        await self.bot.send_message(chat_id=CHAT_ID, text=text)

        csv_path = "v27_trades.csv"
        pd.DataFrame(all_trades).to_csv(csv_path, index=False, encoding='utf-8-sig')
        with open(csv_path, 'rb') as f:
            await self.bot.send_document(chat_id=CHAT_ID, document=f, filename=csv_path,
                                         caption="📎 CSV صفقات V27")
        os.remove(csv_path)

if __name__ == "__main__":
    asyncio.run(SniperV27().run())
