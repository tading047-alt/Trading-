import ccxt
import pandas as pd
import numpy as np
import asyncio
import os
from telegram import Bot

# ==================== إعدادات (معدلة حسب التوصيات) ====================
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

SLIPPAGE = 0.0005
COMMISSION = 0.001
RISK_PER_TRADE = 0.02
INITIAL_CAPITAL = 1000.0
ENTRY_SCORE = 90                # رفع العتبة إلى 90
SYMBOLS_LIMIT = 800
CANDLES_LIMIT = 4000            # زيادة فترة الاختبار إلى 4000 شمعة
MAX_HOLD_CANDLES = 48
TP_ATR_MULT = 2.5               # تعديل نسبة الربح إلى 2.5
SL_ATR_MULT = 1.0
TRAIL_ACTIVATION = 1.5          # تفعيل الوقف المتحرك بعد ربح 1.5 ATR
ADX_THRESHOLD = 25

class BreakoutSniper:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.wallet = INITIAL_CAPITAL
        self.trade_amount = self.wallet * RISK_PER_TRADE

    # ---------------- المؤشرات الفنية ----------------
    def add_indicators(self, df):
        # RSI 14
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # EMA 200
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

        # ATR 14
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()

        # Bollinger Bands
        df['sma20'] = df['close'].rolling(20).mean()
        df['std20'] = df['close'].rolling(20).std()
        df['bb_width'] = (df['std20'] * 4) / df['sma20']

        # ADX 14
        high_diff = df['high'].diff()
        low_diff = df['low'].diff()
        plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0.0)
        minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0.0)
        atr_14 = tr.rolling(14).mean()
        plus_di = 100 * (pd.Series(plus_dm).rolling(14).mean() / atr_14)
        minus_di = 100 * (pd.Series(minus_dm).rolling(14).mean() / atr_14)
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
        df['adx'] = dx.rolling(14).mean()
        return df

    # ---------------- سكور الانفجار (بشرط ADX > 25) ----------------
    def get_breakout_score(self, df, i):
        score = 0
        # فلتر ADX إجباري
        if df['adx'].iloc[i] <= ADX_THRESHOLD:
            return 0

        vol_mean = df['volume'].iloc[max(0, i-20):i].mean()
        if vol_mean > 0 and df['volume'].iloc[i] > vol_mean * 3.0:
            score += 25
        if df['close'].iloc[i] > df['ema200'].iloc[i]:
            score += 25
        if 60 < df['rsi'].iloc[i] < 75:
            score += 25
        min_width_50 = df['bb_width'].iloc[max(0, i-50):i].min()
        if min_width_50 > 0 and df['bb_width'].iloc[i] < min_width_50 * 1.3:
            score += 25
        return score

    # ---------------- محاكاة الصفقة مع وقف متحرك ----------------
    def simulate_trade_exit(self, df, entry_idx, entry_price, tp_price, sl_price, atr):
        trailing_active = False
        trailing_sl = sl_price          # يبدأ بوقف الخسارة الأصلي

        for j in range(entry_idx + 1, min(entry_idx + MAX_HOLD_CANDLES + 1, len(df))):
            high = df['high'].iloc[j]
            low = df['low'].iloc[j]
            close = df['close'].iloc[j]

            # --- تفعيل الوقف المتحرك ---
            if not trailing_active:
                # إذا تحرك السعر لصالحنا بمقدار TRAIL_ACTIVATION * ATR
                if high >= entry_price + (atr * TRAIL_ACTIVATION):
                    trailing_active = True
                    trailing_sl = entry_price   # نقطة التعادل
            else:
                # بعد التفعيل، نرفع الوقف خطوة بخطوة (أعلى قمة - 1 ATR)
                potential_sl = high - (atr * SL_ATR_MULT)
                if potential_sl > trailing_sl:
                    trailing_sl = potential_sl

            # --- فحص الخروج ---
            if low <= trailing_sl:
                return trailing_sl * (1 - SLIPPAGE), 'LOSS'
            if high >= tp_price:
                return tp_price * (1 - SLIPPAGE), 'WIN'

        # خروج اضطراري بعد المدة القصوى
        last_close = df['close'].iloc[min(entry_idx + MAX_HOLD_CANDLES, len(df)-1)]
        return last_close * (1 - SLIPPAGE), 'TIME_EXIT'

    # ---------------- باك تست لعملة واحدة ----------------
    async def backtest_symbol(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=CANDLES_LIMIT)
            df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
            df = self.add_indicators(df)

            trades = []
            for i in range(200, len(df) - MAX_HOLD_CANDLES):
                score = self.get_breakout_score(df, i)
                if score < ENTRY_SCORE:
                    continue

                entry_close = df['close'].iloc[i]
                atr = df['atr'].iloc[i]
                if atr <= 0:
                    continue

                entry_price = entry_close * (1 + SLIPPAGE)
                tp_price = entry_close + (atr * TP_ATR_MULT)
                sl_price = entry_close - (atr * SL_ATR_MULT)

                exit_price, result = self.simulate_trade_exit(
                    df, i, entry_price, tp_price, sl_price, atr
                )

                gross_return = (exit_price / entry_price) - 1
                net_pnl_pct = (gross_return - 2 * COMMISSION) * 100

                trades.append({
                    'symbol': symbol,
                    'result': result,
                    'pnl_pct': round(net_pnl_pct, 4),
                    'score': score
                })
            return trades
        except:
            return []

    # ---------------- إرسال التقرير و CSV ----------------
    async def send_report(self, all_trades):
        if not all_trades:
            await self.bot.send_message(chat_id=CHAT_ID, text="⚠️ لم تُفتح أي صفقة.")
            return

        for trade in all_trades:
            self.wallet += self.trade_amount * (trade['pnl_pct'] / 100)

        wins = [t for t in all_trades if t['result'] == 'WIN']
        losses = [t for t in all_trades if t['result'] == 'LOSS']
        time_exits = [t for t in all_trades if t['result'] == 'TIME_EXIT']
        total = len(all_trades)

        avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
        avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0

        text = (
            f"📊 *نتائج القناص (V23 - محسّن):*\n\n"
            f"💰 الرصيد النهائي: {self.wallet:.2f}$\n"
            f"📈 العائد الصافي: {((self.wallet - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100:.2f}%\n"
            f"🎯 عدد الصفقات: {total}\n"
            f"🏆 نسبة النجاح: {(len(wins) / total * 100):.2f}%\n"
            f"❌ خسائر: {len(losses)} | ⏳ مخارج زمنية: {len(time_exits)}\n"
            f"📊 متوسط الربح: {avg_win:.2f}% | متوسط الخسارة: {avg_loss:.2f}%"
        )
        await self.bot.send_message(chat_id=CHAT_ID, text=text)

        # حفظ وإرسال CSV
        csv_filename = "sniper_backtest_results.csv"
        pd.DataFrame(all_trades).to_csv(csv_filename, index=False)

        try:
            with open(csv_filename, 'rb') as file:
                await self.bot.send_document(
                    chat_id=CHAT_ID,
                    document=file,
                    filename=csv_filename,
                    caption="📎 ملف CSV التفصيلي (V23)"
                )
        finally:
            if os.path.exists(csv_filename):
                os.remove(csv_filename)

    # ---------------- التشغيل الرئيسي ----------------
    async def run(self):
        await self.bot.send_message(chat_id=CHAT_ID, text="🎯 بدء فحص القناص (V23) بمؤشرات محسّنة...")

        markets = self.exchange.load_markets()
        symbols = [s for s in markets if s.endswith('/USDT') and markets[s]['active']]
        symbols = symbols[:SYMBOLS_LIMIT]

        all_trades = []
        batch_size = 50
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i+batch_size]
            tasks = [self.backtest_symbol(sym) for sym in batch]
            results = await asyncio.gather(*tasks)
            for res in results:
                all_trades.extend(res)

        await self.send_report(all_trades)

if __name__ == "__main__":
    asyncio.run(BreakoutSniper().run())
