import ccxt
import pandas as pd
import numpy as np
import time
from datetime import datetime

# --- الإعدادات ---
INITIAL_BALANCE = 100.0
RISK_PER_TRADE = 0.25      # 25% من الرصيد لكل صفقة
COMMISSION = 0.001          # 0.1% عمولة

# --- تهيئة المنصة ---
exchange = ccxt.binance()

# --- دوال المؤشرات الفنية ---
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_bb_width(series, window=20):
    sma = series.rolling(window=window).mean()
    std = series.rolling(window=window).std()
    upper = sma + (std * 2)
    lower = sma - (std * 2)
    return (upper - lower) / sma

# --- فئة البوت الرئيسية ---
class SnowballSniper:
    def __init__(self):
        self.balance = INITIAL_BALANCE
        self.active_trades = {}

    def get_explosive_pairs(self):
        """جلب الأزواج الرشيقة"""
        try:
            tickers = exchange.fetch_tickers()
            heavy = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT']
            filtered = []
            for symbol, data in tickers.items():
                vol = data.get('quoteVolume', 0)
                if symbol.endswith('/USDT') and symbol not in heavy:
                    if 15000000 < vol < 200000000:
                        filtered.append(symbol)
            return filtered[:50]
        except:
            return []

    def analyze(self, df):
        """تحليل البيانات وحساب النتيجة"""
        if len(df) < 50:
            return 0, 0

        df['bbw'] = calculate_bb_width(df['c'])
        df['rsi'] = calculate_rsi(df['c'])

        # حساب انكماش البولينجر
        if len(df) >= 25:
            min_bbw = df['bbw'].iloc[-25:-1].min()
        else:
            min_bbw = df['bbw'].iloc[:-1].min() if len(df) > 1 else df['bbw'].iloc[-1]
        
        current_bbw = df['bbw'].iloc[-1]
        bb_condition = current_bbw < min_bbw

        # حساب اختراق المقاومة
        if len(df) >= 21:
            resistance = df['h'].iloc[-21:-1].max()
        else:
            resistance = df['h'].iloc[:-1].max() if len(df) > 1 else df['h'].iloc[-1]
        
        current_price = df['c'].iloc[-1]
        resistance_condition = current_price > resistance

        # حساب حجم التداول
        avg_volume = df['v'].iloc[-21:-1].mean() if len(df) >= 21 else df['v'].mean()
        volume_condition = df['v'].iloc[-1] > (avg_volume * 2.2)

        # حساب النتيجة
        score = 0
        if bb_condition:
            score += 35
        if resistance_condition:
            score += 35
        if volume_condition:
            score += 30

        return score, current_price

    def run_backtest(self, days=30):
        """تشغيل الاختبار العكسي"""
        print(f"🔍 بدء الاختبار العكسي لآخر {days} يوم...")
        
        pairs = self.get_explosive_pairs()[:15]
        bt_balance = INITIAL_BALANCE
        total_trades = 0
        wins = 0

        for symbol in pairs:
            try:
                print(f"⏳ فحص {symbol}...")
                since = exchange.milliseconds() - (days * 24 * 60 * 60 * 1000)
                bars = exchange.fetch_ohlcv(symbol, '1h', since=since, limit=500)
                
                if len(bars) < 100:
                    continue
                    
                df = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
                
                for i in range(50, len(df) - 25):
                    sub_df = df.iloc[:i+1].copy()
                    score, price = self.analyze(sub_df)
                    
                    if score >= 70:
                        # فتح صفقة
                        position_value = bt_balance * RISK_PER_TRADE
                        target = price * 1.10
                        stop = price * 0.96
                        
                        # مراقبة الـ 24 شمعة التالية
                        future = df.iloc[i+1:i+25]
                        trade_result = None
                        
                        for _, row in future.iterrows():
                            if row['h'] >= target:
                                trade_result = 0.10
                                wins += 1
                                break
                            if row['l'] <= stop:
                                trade_result = -0.04
                                break
                        
                        if trade_result is None and len(future) > 0:
                            # إغلاق عند آخر سعر
                            final_change = (future.iloc[-1]['c'] - price) / price
                            trade_result = final_change
                            if final_change > 0:
                                wins += 1
                        
                        if trade_result is not None:
                            bt_balance += position_value * trade_result
                            bt_balance -= position_value * COMMISSION * 2  # عمولة دخول وخروج
                            total_trades += 1
                            
            except Exception as e:
                print(f"خطأ في {symbol}: {e}")
                continue

        # عرض النتائج
        print("\n" + "="*50)
        print("📊 نتائج الاختبار العكسي")
        print(f"💰 الرصيد النهائي: {bt_balance:.2f} $")
        print(f"📈 إجمالي الصفقات: {total_trades}")
        if total_trades > 0:
            print(f"🎯 نسبة النجاح: {(wins/total_trades)*100:.2f}%")
            print(f"🚀 العائد: {((bt_balance - INITIAL_BALANCE)/INITIAL_BALANCE)*100:.2f}%")
        print("="*50)

    def run_live(self):
        """التداول الحي - وضع المحاكاة"""
        print("🚀 تشغيل البوت في وضع المحاكاة...")
        print("⚠️ للاختبار فقط - لا تداول حقيقي\n")
        
        # جلب الأزواج مرة واحدة
        pairs = self.get_explosive_pairs()[:20]
        print(f"تم العثور على {len(pairs)} زوج للتحليل\n")
        
        for symbol in pairs[:5]:  # اختبر أول 5 أزواج فقط للسرعة
            try:
                print(f"📊 تحليل {symbol}...")
                ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=100)
                df = pd.DataFrame(ohlcv, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
                df['c'] = df['c'].astype(float)
                
                score, price = self.analyze(df)
                print(f"  السعر: {price:.4f} | النتيجة: {score}")
                
                if score >= 70:
                    print(f"  ✅ إشارة شراء! درجة {score}")
                else:
                    print(f"  ❌ لا توجد إشارة")
                    
            except Exception as e:
                print(f"خطأ في {symbol}: {e}")
            
            time.sleep(1)  # تجنب الحظر من المنصة

# --- التشغيل ---
if __name__ == "__main__":
    bot = SnowballSniper()
    
    print("الرجاء الاختيار:")
    print("1 - اختبار عكسي (Backtest)")
    print("2 - تداول حي (محاكاة)")
    
    choice = input("أدخل 1 أو 2: ")
    
    if choice == "1":
        bot.run_backtest(30)
    elif choice == "2":
        bot.run_live()
    else:
        print("اختيار غير صالح")
