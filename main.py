import ccxt
import pandas as pd
import numpy as np
import asyncio
import os
from datetime import datetime, timedelta
from telegram import Bot

# ==================== إعدادات ====================
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

SLIPPAGE = 0.0005
COMMISSION = 0.001
RISK_PER_TRADE = 0.02
INITIAL_CAPITAL = 1000.0
ENTRY_SCORE = 75                # عتبة السكور (مرنة، بعد إضافة مؤشرات جديدة)
SYMBOLS_LIMIT = 800
CANDLES_LIMIT = 4000            # حوالي 5-6 أشهر
MAX_HOLD_CANDLES = 48
TP_ATR_MULT = 2.5
SL_ATR_MULT = 1.0
TRAIL_ACTIVATION = 1.5
ADX_THRESHOLD = 20              # خفضنا العتبة قليلاً لأن المؤشرات الأخرى تساعد

class BreakoutSniper:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.wallet = INITIAL_CAPITAL
        self.trade_amount = self.wallet * RISK_PER_TRADE

    # ---------------- المؤشرات الفنية (موسّعة) ----------------
    def add_indicators(self, df):
        # --- RSI 14 ---
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # --- EMA 200 و EMA 50 ---
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()

        # --- ATR 14 ---
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()

        # --- Bollinger Bands (20,2) ---
        df['sma20'] = df['close'].rolling(20).mean()
        df['std20'] = df['close'].rolling(20).std()
        df['bb_width'] = (df['std20'] * 4) / df['sma20']

        # --- ADX 14 ---
        high_diff = df['high'].diff()
        low_diff = df['low'].diff()
        plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0.0)
        minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0.0)
        atr_14 = tr.rolling(14).mean()
        plus_di = 100 * (pd.Series(plus_dm).rolling(14).mean() / atr_14)
        minus_di = 100 * (pd.Series(minus_dm).rolling(14).mean() / atr_14)
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
        df['adx'] = dx.rolling(14).mean()

        # --- MACD (12,26,9) ---
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd_line'] = ema12 - ema26
        df['macd_signal'] = df['macd_line'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd_line'] - df['macd_signal']

        # --- حجم نسبي (نسبة الحجم إلى متوسط 20 شمعة) ---
        df['volume_sma20'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma20']

        # --- جسم الشمعة (للكشف عن الشموع القوية) ---
        df['body'] = abs(df['close'] - df['open'])
        df['avg_body'] = df['body'].rolling(20).mean()

        return df

    # ---------------- سكور الانفجار (نسخة محسّنة) ----------------
    def get_breakout_score(self, df, i):
        """
        يفحص الشمعة رقم i ويعطي نقاطاً من 0 إلى 100.
        """
        score = 0

        # 1) فلتر ADX إجباري (إن لم يتجاوز الحد الأدنى، لا نكمل)
        if df['adx'].iloc[i] < ADX_THRESHOLD:
            return 0

        # 2) الاتجاه العام: EMA50 > EMA200 (تقاطع ذهبي) -> +20 نقطة
        if df['ema50'].iloc[i] > df['ema200'].iloc[i]:
            score += 20

        # 3) السعر أعلى من EMA200 مباشرة -> +10 (تأكيد إضافي)
        if df['close'].iloc[i] > df['ema200'].iloc[i]:
            score += 10

        # 4) حجم تداول نسبي > 2 -> +20 نقطة (نشاط غير عادي)
        if df['volume_ratio'].iloc[i] > 2.0:
            score += 20
        elif df['volume_ratio'].iloc[i] > 1.5:
            score += 10   # نصف النقاط

        # 5) شمعة صاعدة قوية (جسم أكبر من 1.5 متوسط الأجسام) -> +15
        if (df['close'].iloc[i] > df['open'].iloc[i]) and (df['body'].iloc[i] > df['avg_body'].iloc[i] * 1.5):
            score += 15

        # 6) RSI بين 50 و 70 (زخم صاعد دون تشبع) -> +10
        if 50 < df['rsi'].iloc[i] < 70:
            score += 10

        # 7) ضيق بولينجر (عرض النطاق أقل من 1.2 ضعف أدنى عرض خلال 50 شمعة) -> +15
        min_width_50 = df['bb_width'].iloc[max(0, i-50):i].min()
        if min_width_50 > 0 and df['bb_width'].iloc[i] < min_width_50 * 1.2:
            score += 15

        # 8) MACD إيجابي (الخط فوق الإشارة) -> +10
        if df['macd_line'].iloc[i] > df['macd_signal'].iloc[i]:
            score += 10

        # 9) MACD Histogram في ازدياد (قيمته أكبر من الشمعة السابقة) -> +5
        if i > 0 and df['macd_hist'].iloc[i] > df['macd_hist'].iloc[i-1]:
            score += 5

        return score

    # ---------------- محاكاة الصفقة مع وقف متحرك ----------------
    def simulate_trade_exit(self, df, entry_idx, entry_price, tp_price, sl_price, atr):
        trailing_active = False
        trailing_sl = sl_price
        exit_idx = entry_idx

        for j in range(entry_idx + 1, min(entry_idx + MAX_HOLD_CANDLES + 1, len(df))):
            high = df['high'].iloc[j]
            low = df['low'].iloc[j]

            # تفعيل الوقف المتحرك
            if not trailing_active:
                if high >= entry_price + (atr * TRAIL_ACTIVATION):
                    trailing_active = True
                    trailing_sl = entry_price
            else:
                potential_sl = high - (atr * SL_ATR_MULT)
                if potential_sl > trailing_sl:
                    trailing_sl = potential_sl

            if low <= trailing_sl:
                exit_idx = j
                return trailing_sl * (1 - SLIPPAGE), 'LOSS', j
            if high >= tp_price:
                exit_idx = j
                return tp_price * (1 - SLIPPAGE), 'WIN', j

        # خروج اضطراري
        last_idx = min(entry_idx + MAX_HOLD_CANDLES, len(df)-1)
        return df['close'].iloc[last_idx] * (1 - SLIPPAGE), 'TIME_EXIT', last_idx

    # ---------------- باك تست لعملة واحدة (مع تفاصيل CSV) ----------------
    async def backtest_symbol(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe='1h', limit=CANDLES_LIMIT)
            df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')  # تحويل لوقت قابل للقراءة
            df = self.add_indicators(df)

            trades = []
            for i in range(200, len(df) - MAX_HOLD_CANDLES):
                score = self.get_breakout_score(df, i)
                if score < ENTRY_SCORE:
                    continue

                atr = df['atr'].iloc[i]
                if atr <= 0:
                    continue

                entry_close = df['close'].iloc[i]
                entry_time = df['timestamp'].iloc[i]
                entry_price = entry_close * (1 + SLIPPAGE)
                tp_price = entry_close + (atr * TP_ATR_MULT)
                sl_price = entry_close - (atr * SL_ATR_MULT)

                exit_price, result, exit_idx = self.simulate_trade_exit(
                    df, i, entry_price, tp_price, sl_price, atr
                )
                exit_time = df['timestamp'].iloc[exit_idx]
                duration_hours = (exit_time - entry_time).total_seconds() / 3600.0

                gross_return = (exit_price / entry_price) - 1
                net_pnl_pct = (gross_return - 2 * COMMISSION) * 100

                trades.append({
                    'symbol': symbol,
                    'entry_time': entry_time.strftime('%Y-%m-%d %H:%M'),
                    'exit_time': exit_time.strftime('%Y-%m-%d %H:%M'),
                    'duration_hours': round(duration_hours, 2),
                    'entry_price': round(entry_price, 8),
                    'exit_price': round(exit_price, 8),
                    'result': result,
                    'pnl_pct': round(net_pnl_pct, 4),
                    'score': score
                })
            return trades
        except Exception as e:
            # print(f"Error {symbol}: {e}")
            return []

    # ---------------- إرسال التقرير و CSV ----------------
    async def send_report(self, all_trades):
        if not all_trades:
            await self.bot.send_message(chat_id=CHAT_ID, text="⚠️ لم تُفتح أي صفقة. جرب خفض عتبة السكور أو تعديل الفلاتر.")
            return

        # حساب الرصيد
        for trade in all_trades:
            self.wallet += self.trade_amount * (trade['pnl_pct'] / 100)

        wins = [t for t in all_trades if t['result'] == 'WIN']
        losses = [t for t in all_trades if t['result'] == 'LOSS']
        time_exits = [t for t in all_trades if t['result'] == 'TIME_EXIT']
        total = len(all_trades)

        avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
        avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
        avg_duration = np.mean([t['duration_hours'] for t in all_trades])

        # تقرير نصي
        text = (
            f"📊 *نتائج القناص (V24 - سكور متطور):*\n\n"
            f"💰 الرصيد النهائي: {self.wallet:.2f}$\n"
            f"📈 العائد الصافي: {((self.wallet - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100:.2f}%\n"
            f"🎯 عدد الصفقات: {total}\n"
            f"🏆 نسبة النجاح: {(len(wins) / total * 100):.2f}%\n"
            f"❌ خسائر: {len(losses)} | ⏳ مخارج زمنية: {len(time_exits)}\n"
            f"📊 متوسط الربح: {avg_win:.2f}% | متوسط الخسارة: {avg_loss:.2f}%\n"
            f"⏱️ متوسط مدة الصفقة: {avg_duration:.1f} ساعة"
        )
        await self.bot.send_message(chat_id=CHAT_ID, text=text)

        # CSV
        csv_filename = "sniper_v24_trades.csv"
        df_csv = pd.DataFrame(all_trades)
        df_csv = df_csv[['symbol', 'entry_time', 'exit_time', 'duration_hours',
                         'entry_price', 'exit_price', 'result', 'pnl_pct', 'score']]
        df_csv.to_csv(csv_filename, index=False, encoding='utf-8-sig')

        try:
            with open(csv_filename, 'rb') as file:
                await self.bot.send_document(
                    chat_id=CHAT_ID,
                    document=file,
                    filename=csv_filename,
                    caption="📎 ملف CSV تفصيلي بجميع الصفقات (V24)"
                )
        finally:
            if os.path.exists(csv_filename):
                os.remove(csv_filename)

    # ---------------- التشغيل -----------------
    async def run(self):
        await self.bot.send_message(chat_id=CHAT_ID, text="🎯 بدء فحص القناص (V24) بمؤشرات متطورة وسكور محسّن...")

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
