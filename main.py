import ccxt
import pandas as pd
import numpy as np
import asyncio
from telegram import Bot

# ==================== إعدادات (يمكنك تعديلها هنا) ====================
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

SLIPPAGE = 0.0005          # انزلاق سعري 0.05%
COMMISSION = 0.001         # عمولة 0.1% لكل صفقة (تضرب ×2 للدخول والخروج)
RISK_PER_TRADE = 0.02      # نسبة المخاطرة من الرصيد (2%)
INITIAL_CAPITAL = 1000.0   # رأس المال الابتدائي
ENTRY_SCORE = 82           # عتبة السكور للدخول
SYMBOLS_LIMIT = 800        # عدد العملات التي تفحصها
CANDLES_LIMIT = 740        # عدد الشموع المسترجعة
MAX_HOLD_CANDLES = 48      # أقصى مدة للصفقة بالساعات

class BreakoutSniper:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.wallet = INITIAL_CAPITAL
        self.trade_amount = self.wallet * RISK_PER_TRADE

    # ---------------- حساب المؤشرات الفنية ----------------
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

        # Bollinger Bands (20,2) – عرض النطاق
        df['sma20'] = df['close'].rolling(20).mean()
        df['std20'] = df['close'].rolling(20).std()
        df['bb_width'] = (df['std20'] * 4) / df['sma20']
        return df

    # ---------------- حساب سكور الانفجار ----------------
    def get_breakout_score(self, df, i):
        score = 0
        # 1) حجم تداول > 3 أضعاف المتوسط
        vol_mean = df['volume'].iloc[max(0, i-20):i].mean()
        if vol_mean > 0 and df['volume'].iloc[i] > vol_mean * 3.0:
            score += 25
        # 2) السعر فوق EMA200 (اتجاه صاعد)
        if df['close'].iloc[i] > df['ema200'].iloc[i]:
            score += 25
        # 3) RSI بين 60 و 75 (زخم شرائي دون تشبع)
        if 60 < df['rsi'].iloc[i] < 75:
            score += 25
        # 4) انفجار من ضيق بولينجر (أقل من 1.3 ضعف أدنى عرض سابق)
        min_width_50 = df['bb_width'].iloc[max(0, i-50):i].min()
        if min_width_50 > 0 and df['bb_width'].iloc[i] < min_width_50 * 1.3:
            score += 25
        return score

    # ---------------- محاكاة خروج الصفقة بواقعية ----------------
    def simulate_trade_exit(self, df, entry_idx, entry_price, tp_price, sl_price):
        for j in range(entry_idx + 1, min(entry_idx + MAX_HOLD_CANDLES + 1, len(df))):
            high = df['high'].iloc[j]
            low = df['low'].iloc[j]
            # الأولوية للوقف (يفترض أنه يضرب أولاً لو تحقق الاثنان)
            if low <= sl_price:
                return sl_price * (1 - SLIPPAGE), 'LOSS'
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

                entry_price = entry_close * (1 + SLIPPAGE)      # سعر الشراء مع الانزلاق
                tp_price = entry_close + (atr * 3.0)
                sl_price = entry_close - (atr * 1.0)

                exit_price, result = self.simulate_trade_exit(df, i, entry_price, tp_price, sl_price)

                # صافي العائد بعد خصم العمولتين
                gross_return = (exit_price / entry_price) - 1
                net_pnl_pct = (gross_return - 2 * COMMISSION) * 100

                trades.append({
                    'symbol': symbol,
                    'result': result,
                    'pnl_pct': net_pnl_pct,
                    'score': score
                })
            return trades
        except:
            return []

    # ---------------- إرسال التقرير إلى تيليجرام ----------------
    async def send_report(self, all_trades):
        if not all_trades:
            await self.bot.send_message(chat_id=CHAT_ID, text="⚠️ لم تُفتح أي صفقة. جرب خفض عتبة السكور.")
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
            f"📊 *نتائج القناص (نسخة واقعية):*\n\n"
            f"💰 الرصيد النهائي: {self.wallet:.2f}$\n"
            f"📈 العائد الصافي: {((self.wallet - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100:.2f}%\n"
            f"🎯 عدد الصفقات: {total}\n"
            f"🏆 نسبة النجاح: {(len(wins) / total * 100):.2f}%\n"
            f"❌ خسائر: {len(losses)} | ⏳ مخارج زمنية: {len(time_exits)}\n"
            f"📊 متوسط الربح: {avg_win:.2f}% | متوسط الخسارة: {avg_loss:.2f}%"
        )
        await self.bot.send_message(chat_id=CHAT_ID, text=text)

    # ---------------- التشغيل الرئيسي ----------------
    async def run(self):
        await self.bot.send_message(chat_id=CHAT_ID, text="🎯 بدء فحص القناص... انتظر التقرير.")

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


# ==================== تشغيل ====================
if __name__ == "__main__":
    asyncio.run(BreakoutSniper().run())
