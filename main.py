import ccxt
import pandas as pd
import numpy as np
import asyncio
import os
from telegram import Bot

# ==================== إعدادات V31 ====================
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

SLIPPAGE = 0.0005
COMMISSION = 0.001
RISK_PER_TRADE = 0.02
INITIAL_CAPITAL = 1000.0

SYMBOLS_LIMIT = 800
CANDLES_LIMIT = 4000
MAX_HOLD_CANDLES = 48

# --- معاملات استراتيجية الاندماج ---
TP_RANGE_MULT = 2.5         # الهدف = 2.5x نطاق شمعة الاشتعال
TRAIL_ACTIVATION_MULT = 2.0 # تفعيل التعادل بعد 2x نطاق الاشتعال
MIN_VOLUME_RATIO = 2.5      # الحد الأدنى لنسبة الحجم
MIN_ADX = 20                # الحد الأدنى لـ ADX

EXCLUDED_ASSETS = {'BTC', 'ETH'}
STABLECOINS = {'USDC', 'BUSD', 'USDP', 'TUSD', 'DAI', 'USDD', 'FDUSD', 'USTC'}

class FusionSniperV31:
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

    # ---------------- المؤشرات الأساسية فقط ----------------
    def add_indicators(self, df):
        # EMA 200
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        # ADX 14
        hl = df['high'] - df['low']
        hc = (df['high'] - df['close'].shift()).abs()
        lc = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean()
        
        hd = df['high'].diff()
        ld = df['low'].diff()
        pdm = np.where((hd > ld) & (hd > 0), hd, 0.0)
        ndm = np.where((ld > hd) & (ld > 0), ld, 0.0)
        pdi = 100 * (pd.Series(pdm).rolling(14).mean() / atr14)
        ndi = 100 * (pd.Series(ndm).rolling(14).mean() / atr14)
        dx = (abs(pdi - ndi) / (pdi + ndi)) * 100
        df['adx'] = dx.rolling(14).mean()

        # حجم نسبي
        df['vol_sma20'] = df['volume'].rolling(20).mean()
        df['vol_ratio'] = df['volume'] / df['vol_sma20']
        
        # نطاق الشمعة (Range)
        df['range'] = df['high'] - df['low']
        return df

    # ---------------- محاكاة الخروج ----------------
    def simulate_exit(self, df, entry_idx, entry_price, tp, ignition_range, sl_price):
        trailing_active = False
        trailing_sl = sl_price

        for j in range(entry_idx, min(entry_idx + MAX_HOLD_CANDLES, len(df))):
            high, low = df['high'].iloc[j], df['low'].iloc[j]

            if not trailing_active:
                if high >= entry_price + (ignition_range * TRAIL_ACTIVATION_MULT):
                    trailing_active = True
                    trailing_sl = entry_price # التعادل
            else:
                potential_sl = high - ignition_range
                if potential_sl > trailing_sl:
                    trailing_sl = potential_sl

            if low <= trailing_sl:
                return trailing_sl * (1 - SLIPPAGE), 'LOSS', j
            if high >= tp:
                return tp * (1 - SLIPPAGE), 'WIN', j

        last = min(entry_idx + MAX_HOLD_CANDLES, len(df) - 1)
        return df['close'].iloc[last] * (1 - SLIPPAGE), 'TIME_EXIT', last

    # ---------------- باك تست لعملة واحدة ----------------
    async def backtest_symbol(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, '1h', limit=CANDLES_LIMIT)
            df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
            df.columns = ['timestamp','open','high','low','close','volume']
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = self.add_indicators(df)

            trades = []
            for i in range(50, len(df) - MAX_HOLD_CANDLES - 1):
                
                # 1. فلتر إتجاه (EMA200 و ADX)
                if df['close'].iloc[i] <= df['ema200'].iloc[i]: continue
                if df['adx'].iloc[i] < MIN_ADX: continue

                # 2. تحديد أضيق نطاق (Squeeze) خلال 20 شمعة
                recent_ranges = df['range'].iloc[max(0, i-20):i]
                if recent_ranges.empty: continue
                min_range = recent_ranges.min()
                
                # 3. شمعة الاشتعال (Ignition)
                # يجب أن تكون شمعة خضراء، تخترق أعلى قمة للنطاقات الهادئة، وبحجم كبير
                is_green = df['close'].iloc[i] > df['open'].iloc[i]
                is_volume_surge = df['vol_ratio'].iloc[i] > MIN_VOLUME_RATIO
                
                # لتحديد الاختراق، نقارن بأعلى قمة خلال فترة الانضغاط
                highest_high_in_squeeze = df['high'].iloc[max(0, i-20):i].max()
                is_breakout = df['high'].iloc[i] > highest_high_in_squeeze

                if not (is_green and is_volume_surge and is_breakout): continue

                # 4. تأكيد الكسر (الدخول عند كسر قمة شمعة الاشتعال)
                entry_price = df['high'].iloc[i] * (1 + SLIPPAGE)
                
                # حساب الوقف والهدف بناءً على نطاق شمعة الاشتعال
                ignition_range = df['range'].iloc[i]
                sl_price = df['low'].iloc[i] * (1 - SLIPPAGE)  # الوقف هو قاع الشمعة
                tp = entry_price + (ignition_range * TP_RANGE_MULT)

                # محاكاة الخروج
                exit_price, result, exit_idx = self.simulate_exit(df, i+1, entry_price, tp, ignition_range, sl_price)
                
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
                    'score': 'price_action'
                })
            return trades
        except:
            return []

    # ---------------- التشغيل الرئيسي ----------------
    async def run(self):
        await self.bot.send_message(chat_id=CHAT_ID, text="🎯 V31: القناص الاندماجي (Price Action + Indicators)...")

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
            trade_return = (t['pnl_pct'] / 100) * RISK_PER_TRADE
            wallet *= (1 + trade_return)

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
            f"📊 *V31 - القناص الاندماجي (PA):*\n\n"
            f"💰 النهائي: {wallet:.2f}$ ({((wallet/INITIAL_CAPITAL)-1)*100:.2f}%)\n"
            f"🎯 الصفقات: {len(all_trades)}\n"
            f"🏆 نجاح: {(len(wins)/len(all_trades)*100):.2f}% ({len(wins)})\n"
            f"❌ خسائر: {len(losses)} | ⏳ زمنية: {len(exits)}\n"
            f"📊 متوسط ربح: {avg_win:.2f}% | خسارة: {avg_loss:.2f}%\n"
            f"📐 عامل الربح: {profit_factor:.2f}\n"
            f"⏱️ متوسط المدة: {avg_dur:.1f}h"
        )
        await self.bot.send_message(chat_id=CHAT_ID, text=text)

        csv_path = "v31_trades.csv"
        pd.DataFrame(all_trades).to_csv(csv_path, index=False, encoding='utf-8-sig')
        with open(csv_path, 'rb') as f:
            await self.bot.send_document(chat_id=CHAT_ID, document=f,
                                         filename=csv_path, caption="📎 CSV صفقات V31")
        os.remove(csv_path)

if __name__ == "__main__":
    asyncio.run(FusionSniperV31().run())
