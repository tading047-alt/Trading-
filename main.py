import ccxt
import pandas as pd
import numpy as np
import asyncio
import os
from telegram import Bot

# ==================== إعدادات V35 ====================
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

SLIPPAGE = 0.0005
COMMISSION = 0.001
RISK_PER_TRADE = 0.02
INITIAL_CAPITAL = 1000.0

SYMBOLS_LIMIT = 1200
CANDLES_LIMIT = 8000
MAX_HOLD_CANDLES = 72

# --- معاملات استراتيجية بصمة الانفجار ---
CONTRACTION_BODY_RATIO = 0.3      # الأجسام أقل من 30% من النطاق = انكماش
CONTRACTION_PERIOD = 15            # عدد شموع الانكماش المطلوبة
VOLUME_RISE_RATIO = 1.5           # ارتفاع الحجم 50% فوق المتوسط = تراكم
REVERSAL_ENGULF_RATIO = 1.2       # شمعة الابتلاع أكبر بـ 20% من سابقتها
MSB_PERIOD = 50                    # فترة البحث عن أعلى قمة سابقة

TP_RANGE_MULT = 3.0               # الهدف = 3x متوسط المدى
SL_RANGE_MULT = 1.0               # الوقف = 1x متوسط المدى

EXCLUDED_ASSETS = {'BTC', 'ETH'}
STABLECOINS = {'USDC', 'BUSD', 'USDP', 'TUSD', 'DAI', 'USDD', 'FDUSD', 'USTC'}

class FingerprintSniperV35:
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

    def add_fingerprint_indicators(self, df):
        """مؤشرات خاصة بكشف بصمة الانفجار"""
        
        # أساسيات الشمعة
        df['range'] = df['high'] - df['low']
        df['body'] = abs(df['close'] - df['open'])
        df['body_ratio'] = df['body'] / df['range'].replace(0, np.nan)
        df['upper_shadow'] = df['high'] - df[['close', 'open']].max(axis=1)
        df['lower_shadow'] = df[['close', 'open']].min(axis=1) - df['low']
        
        # حجم نسبي
        df['vol_sma20'] = df['volume'].rolling(20).mean()
        df['vol_ratio'] = df['volume'] / df['vol_sma20']
        
        # هل الشمعة خضراء؟
        df['is_green'] = df['close'] > df['open']
        df['is_red'] = df['close'] < df['open']
        
        # أعلى قمة خلال فترة MSB
        df['msb_high'] = df['high'].rolling(MSB_PERIOD).max()
        
        # متوسط المدى للانكماش
        df['avg_range'] = df['range'].rolling(CONTRACTION_PERIOD).mean()
        
        return df

    def detect_explosion_fingerprint(self, df, i):
        """
        يفحص الشمعة i والشمعة i-1 بحثاً عن بصمة الانفجار الرباعية.
        يعيد (True, score) إذا تم اكتشافها، (False, 0) إذا لم تكتشف.
        """
        if i < CONTRACTION_PERIOD + 5:
            return False, 0
        
        score = 0
        
        # ===== البصمة 1: الانكماش (15 شمعة سابقة) =====
        recent_body_ratios = df['body_ratio'].iloc[i-CONTRACTION_PERIOD:i]
        avg_body_ratio = recent_body_ratios.mean()
        
        # الأجسام صغيرة جداً = تردد = انكماش
        if avg_body_ratio < CONTRACTION_BODY_RATIO:
            score += 25
        elif avg_body_ratio < 0.4:
            score += 15
        
        # ===== البصمة 2: التراكم الصامت =====
        # الحجم يرتفع تدريجياً خلال الانكماش دون حركة سعرية كبيرة
        recent_volumes = df['vol_ratio'].iloc[i-CONTRACTION_PERIOD:i]
        recent_ranges = df['range'].iloc[i-CONTRACTION_PERIOD:i]
        
        vol_trend_up = recent_volumes.iloc[-5:].mean() > recent_volumes.iloc[:5].mean() * VOLUME_RISE_RATIO
        range_stable = recent_ranges.std() / recent_ranges.mean() < 0.3  # مدى مستقر
        
        if vol_trend_up and range_stable:
            score += 30
        elif vol_trend_up:
            score += 15
        
        # ===== البصمة 3: الابتلاع العكسي =====
        # شمعة حمراء صغيرة (i-1) < شمعة خضراء كبيرة (i)
        if i >= 1:
            prev_body = df['body'].iloc[i-1]
            curr_body = df['body'].iloc[i]
            
            is_reversal = (
                df['is_red'].iloc[i-1] and      # السابقة حمراء
                df['is_green'].iloc[i] and       # الحالية خضراء
                curr_body > prev_body * REVERSAL_ENGULF_RATIO and  # الجسم الحالي أكبر
                df['close'].iloc[i] > df['open'].iloc[i-1]          # إغلاق فوق افتتاح السابقة
            )
            
            if is_reversal:
                score += 25
            elif df['is_green'].iloc[i] and curr_body > prev_body:
                score += 10
        
        # ===== البصمة 4: كسر هيكل السوق =====
        # السعر الحالي يكسر أعلى قمة خلال 50 شمعة
        if df['high'].iloc[i] >= df['msb_high'].iloc[i] * 0.99:
            score += 20
        elif df['close'].iloc[i] > df['msb_high'].iloc[max(0, i-10)]:
            score += 10
        
        # نجاح الكشف يتطلب 3 من 4 بصمات (75 نقطة)
        detected = score >= 75
        
        return detected, min(score, 100)

    def simulate_exit(self, df, entry_idx, entry_price, tp, sl):
        """خروج بسيط: وقف وهدف ثابتان"""
        for j in range(entry_idx + 1, min(entry_idx + MAX_HOLD_CANDLES, len(df))):
            high, low = df['high'].iloc[j], df['low'].iloc[j]
            
            if low <= sl:
                return sl * (1 - SLIPPAGE), 'LOSS', j
            if high >= tp:
                return tp * (1 - SLIPPAGE), 'WIN', j
        
        last = min(entry_idx + MAX_HOLD_CANDLES, len(df) - 1)
        return df['close'].iloc[last] * (1 - SLIPPAGE), 'TIME_EXIT', last

    async def backtest_symbol(self, symbol):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, '1h', limit=CANDLES_LIMIT)
            df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
            df.columns = ['timestamp','open','high','low','close','volume']
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = self.add_fingerprint_indicators(df)

            trades = []
            start_idx = CONTRACTION_PERIOD + 50
            
            for i in range(start_idx, len(df) - MAX_HOLD_CANDLES - 1):
                detected, score = self.detect_explosion_fingerprint(df, i)
                
                if not detected:
                    continue

                avg_range = df['avg_range'].iloc[i]
                if avg_range <= 0:
                    continue

                # الدخول عند افتتاح الشمعة التالية
                entry_price = df['open'].iloc[i+1] * (1 + SLIPPAGE)
                
                # الوقف والهدف مبنيان على متوسط المدى
                stop_loss = entry_price - (avg_range * SL_RANGE_MULT)
                take_profit = entry_price + (avg_range * TP_RANGE_MULT)

                exit_price, result, exit_idx = self.simulate_exit(df, i+1, entry_price, take_profit, stop_loss)
                
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
                    'score': score,
                    'method': 'fingerprint'
                })
            return trades
        except:
            return []

    async def run(self):
        await self.bot.send_message(chat_id=CHAT_ID, text="🔬 V35: كاشف بصمة الانفجار (طريقة جديدة كلياً)...")

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
            await self.bot.send_message(chat_id=CHAT_ID, text="⚠️ لا توجد صفقات. ربما تحتاج إلى تخفيف شروط الكشف.")
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

        months = CANDLES_LIMIT / (24 * 30)
        annual_return = ((wallet / INITIAL_CAPITAL) - 1) / months * 12 * 100

        text = (
            f"🔬 *V35 - بصمة الانفجار:*\n\n"
            f"💰 النهائي: {wallet:.2f}$ ({((wallet/INITIAL_CAPITAL)-1)*100:.2f}%)\n"
            f"📈 عائد سنوي تقريبي: {annual_return:.2f}%\n"
            f"🎯 الصفقات: {len(all_trades)}\n"
            f"🏆 نجاح: {(len(wins)/len(all_trades)*100):.2f}% ({len(wins)})\n"
            f"❌ خسائر: {len(losses)} | ⏳ زمنية: {len(exits)}\n"
            f"📊 متوسط ربح: {avg_win:.2f}% | خسارة: {avg_loss:.2f}%\n"
            f"📐 عامل الربح: {profit_factor:.2f}\n"
            f"⏱️ متوسط المدة: {avg_dur:.1f}h\n"
            f"🕒 الفترة: {months:.1f} أشهر"
        )
        await self.bot.send_message(chat_id=CHAT_ID, text=text)

        csv_path = "v35_fingerprint_trades.csv"
        pd.DataFrame(all_trades).to_csv(csv_path, index=False, encoding='utf-8-sig')
        with open(csv_path, 'rb') as f:
            await self.bot.send_document(chat_id=CHAT_ID, document=f,
                                         filename=csv_path, caption="📎 CSV صفقات V35 (بصمة الانفجار)")
        os.remove(csv_path)

if __name__ == "__main__":
    asyncio.run(FingerprintSniperV35().run())
