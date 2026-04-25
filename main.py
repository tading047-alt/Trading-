import ccxt
import pandas as pd
import numpy as np
import time
import requests
import os
from datetime import datetime

# --- الإعدادات الشخصية ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'
INITIAL_BALANCE = 100.0
CSV_FILE = 'opportunity_study.csv'
RISK_PER_TRADE = 0.25      # 25% من الرصيد لكل صفقة
COMMISSION = 0.001          # 0.1% عمولة

# --- إعدادات المنصة ---
exchange = ccxt.binance()

# --- دوال الحسابات الفنية ---
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_bb_width(series, window=20):
    sma = series.rolling(window=window).mean()
    std = series.rolling(window=window).std()
    upper = sma + (std * 2)
    lower = sma - (std * 2)
    return (upper - lower) / sma

def send_telegram(message):
    """إرسال رسالة إلى تليجرام (اختياري)"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {'chat_id': CHAT_ID, 'text': message}
        requests.post(url, json=payload, timeout=5)
    except:
        pass

class SnowballSniper:
    def __init__(self):
        self.balance = INITIAL_BALANCE
        self.active_trades = {}   # {symbol: {'entry_price': , 'entry_time': , 'target': , 'stop': , 'amount':}}
        self.last_report_time = time.time()
        if not os.path.exists(CSV_FILE):
            pd.DataFrame(columns=['Time', 'Symbol', 'Price', 'Score', 'Status', 'Result_Pct']).to_csv(CSV_FILE, index=False)

    def get_explosive_pairs(self, limit=80):
        """جلب الأزواج الرشيقة حسب حجم التداول"""
        try:
            tickers = exchange.fetch_tickers()
            heavy_weights = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT']
            filtered = []
            for symbol, data in tickers.items():
                vol = data.get('quoteVolume', 0)
                if symbol.endswith('/USDT') and symbol not in heavy_weights:
                    if 15000000 < vol < 200000000:
                        filtered.append(symbol)
            return filtered[:limit]
        except Exception as e:
            print(f"خطأ في جلب الأزواج: {e}")
            return []

    def analyze_dataframe(self, df):
        """
        تحليل البيانات وإرجاع النتيجة (score) وسعر الإغلاق الحالي.
        التأكد من وجود بيانات كافية.
        """
        if len(df) < 50:
            return 0, 0

        df['bbw'] = calculate_bb_width(df['c'])
        df['rsi'] = calculate_rsi(df['c'])

        # حساب أقل عرض بولينجر في آخر 24 شمعة (قبل الشمعة الحالية)
        if len(df) >= 25:
            min_bbw_last24 = df['bbw'].iloc[-25:-1].min()
        else:
            min_bbw_last24 = df['bbw'].iloc[:-1].min() if len(df) > 1 else df['bbw'].iloc[-1]

        current_bbw = df['bbw'].iloc[-1]

        # المقاومة: أعلى سعر في آخر 20 شمعة (قبل الشمعة الحالية)
        if len(df) >= 21:
            resistance = df['h'].iloc[-21:-1].max()
        else:
            resistance = df['h'].iloc[:-1].max() if len(df) > 1 else df['h'].iloc[-1]

        current_price = df['c'].iloc[-1]
        avg_volume = df['v'].iloc[-21:-1].mean() if len(df) >= 21 else df['v'].mean()
        current_volume = df['v'].iloc[-1]

        score = 0
        # الشرط 1: انكماش البولينجر
        if current_bbw < min_bbw_last24:
            score += 35
        # الشرط 2: اختراق المقاومة
        if current_price > resistance:
            score += 35
        # الشرط 3: حجم تداول كبير
        if current_volume > (avg_volume * 2.2):
            score += 30

        return score, current_price

    def run_backtest(self, days=30):
        """اختبار عكسي تاريخي محسّن"""
        print(f"🔍 جاري بدء الاختبار العكسي لآخر {days} يوم...")
        pairs = self.get_explosive_pairs(limit=15)   # اختبر أفضل 15 زوجاً
        if not pairs:
            print("لم يتم العثور على أزواج مناسبة.")
            return

        bt_balance = INITIAL_BALANCE
        total_trades = 0
        wins = 0
        # سجل التفاصيل
        trades_log = []

        for symbol in pairs:
            try:
                print(f"⏳ فحص تاريخ {symbol}...")
                since = exchange.milliseconds() - (days * 24 * 60 * 60 * 1000)
                bars = exchange.fetch_ohlcv(symbol, timeframe='1h', since=since, limit=1000)
                if len(bars) < 200:
                    continue
                df_hist = pd.DataFrame(bars, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
                df_hist['ts'] = pd.to_datetime(df_hist['ts'], unit='ms')

                # محاكاة التداول شمعة بشمعة
                for i in range(50, len(df_hist) - 24):
                    sub_df = df_hist.iloc[:i+1].copy()
                    score, price = self.analyze_dataframe(sub_df)

                    if score >= 70:
                        # دخول صفقة
                        entry_price = price
                        # حجم الصفقة = نسبة المخاطرة * الرصيد الحالي
                        position_value = bt_balance * RISK_PER_TRADE
                        # كمية العملة (بدون عمولة)
                        amount = position_value / entry_price

                        target = entry_price * 1.10
                        stop = entry_price * 0.96

                        # مراقبة الـ 24 شمعة التالية
                        future_bars = df_hist.iloc[i+1 : i+25]
                        trade_closed = False
                        final_pct = 0

                        for idx, row in future_bars.iterrows():
                            # تحقق من الوصول إلى الهدف أو الوقف
                            if row['h'] >= target:
                                pct = 0.10
                                final_pct = pct
                                bt_balance += position_value * pct  # الربح
                                # خصم العمولة على الدخول والخروج
                                bt_balance -= (position_value * COMMISSION) + (position_value * 1.10 * COMMISSION)
                                wins += 1
                                trade_closed = True
                                break
                            if row['l'] <= stop:
                                pct = -0.04
                                final_pct = pct
                                bt_balance += position_value * pct  # الخسارة
                                bt_balance -= (position_value * COMMISSION) + (position_value * 0.96 * COMMISSION)
                                trade_closed = True
                                break

                        if not trade_closed:
                            # إغلاق الصفقة بعد 24 ساعة بسعر الإغلاق الأخير
                            final_price = future_bars.iloc[-1]['c']
                            pct = (final_price - entry_price) / entry_price
                            final_pct = pct
                            bt_balance += position_value * pct
                            bt_balance -= (position_value * COMMISSION) + (position_value * (1+pct) * COMMISSION)
                            if pct > 0:
                                wins += 1

                        total_trades += 1
                        trades_log.append({
                            'symbol': symbol,
                            'entry_time': df_hist.iloc[i]['ts'],
                            'entry_price': entry_price,
                            'exit_pct': final_pct,
                            'balance_after': bt_balance
                        })

            except Exception as e:
                print(f"خطأ في {symbol}: {e}")
                continue

        # النتائج النهائية
        print("\n" + "="*50)
        print(f"📊 تقرير الاختبار العكسي (Backtest) - {days} يوم")
        print(f"💰 الرصيد النهائي: {bt_balance:.2f} $")
        print(f"📈 إجمالي الصفقات: {total_trades}")
        if total_trades > 0:
            win_rate = (wins / total_trades) * 100
            print(f"🎯 نسبة النجاح: {win_rate:.2f}%")
            print(f"🚀 نمو المحفظة: {((bt_balance - INITIAL_BALANCE)/INITIAL_BALANCE)*100:.2f}%")
        else:
            print("لم يتم تنفيذ أي صفقة.")
        print("="*50)

        # حفظ السجل للتحليل
        if trades_log:
            log_df = pd.DataFrame(trades_log)
            log_df.to_csv('backtest_log.csv', index=False)
            print("✅ تم حفظ تفاصيل الصفقات في backtest_log.csv")

    def run_live(self):
        """التداول الحي - مراقبة وتحليل دوري وإدارة الصفقات المفتوحة"""
        print("🚀 البوت يعمل الآن في الوضع الحي...")
        print("⚠️ تذكر: هذا الكود لأغراض تعليمية. لا تخاطر بأموال حقيقية دون اختبار كافٍ.")
        print("سيتم فحص الأزواج كل 60 دقيقة وفتح صفقات جديدة إذا تحققت الشروط.\n")

        # حلقة لا نهائية
        while True:
            try:
                # 1. تحديث حالة الصفقات المفتوحة (جني أرباح أو وقف خسارة)
                self.update_open_trades()

                # 2. البحث عن أزواج جديدة للدخول
                explosive_pairs = self.get_explosive_pairs(limit=50)
                print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] فحص {len(explosive_pairs)} زوجاً...")

                for symbol in explosive_pairs:
                    # تخطى الأزواج المفتوحة بالفعل
                    if symbol in self.active_trades:
                        continue

                    # جلب آخر 100 شمعة ساعة
                    try:
                        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
                        if len(ohlcv) < 50:
                            continue
                        df = pd.DataFrame(ohlcv, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
                        df['c'] = df['c'].astype(float)
                        df['h'] = df['h'].astype(float)
                        df['l'] = df['l'].astype(float)
                        df['v'] = df['v'].astype(float)

                        score, price = self.analyze_dataframe(df)
                        if score >= 70:
                            print(f"🎯 إشارة شراء على {symbol} | السعر: {price:.4f} | النتيجة: {score}")
                            # تنفيذ صفقة شراء (هنا مجرد محاكاة، يمكنك استبدالها بأمر حقيقي)
                            self.enter_trade(symbol, price)
                            # إرسال إشعار تليجرام (اختياري)
                            # send_telegram(f"🟢 شراء {symbol} بسعر {price}")
                    except Exception as e:
                        print(f"خطأ في تحليل {symbol}: {e}")
                        continue

                # 3. انتظار حتى الساعة التالية (3600 ثانية) أو يمكن ضبط وقت أقل للتجربة
                print(f"⏳ انتظار 60 دقيقة حتى الفحص التالي...")
                time.sleep(3600)

            except KeyboardInterrupt:
                print("\n🔴 تم إيقاف البوت بواسطة المستخدم.")
                break
            except Exception as e:
                print(f"خطأ عام: {e}")
                time.sleep(60)

    def enter_trade(self, symbol, price):
        """فتح صفقة جديدة (محاكاة)"""
        position_value = self.balance * RISK_PER_TRADE
        amount = position_value / price
        target = price * 1.10
        stop = price * 0.96

        self.active_trades[symbol] = {
            'entry_price': price,
            'entry_time': time.time(),
            'target': target,
            'stop': stop,
            'amount': amount,
            'position_value': position_value
        }
        # خصم العمولة عند الدخول
        self.balance -= position_value * COMMISSION
        print(f"✅ تم فتح صفقة على {symbol} بسعر {price:.4f} | الهدف: {target:.4f} | الوقف: {stop:.4f}")
        # تسجيل في CSV
        new_row = pd.DataFrame([{
            'Time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'Symbol': symbol,
            'Price': price,
            'Score': 'N/A',
            'Status': 'OPEN',
            'Result_Pct': ''
        }])
        new_row.to_csv(CSV_FILE, mode='a', header=False, index=False)

    def update_open_trades(self):
        """تحديث الصفقات المفتوحة: التحقق من الوصول للهدف أو الوقف"""
        if not self.active_trades:
            return

        symbols_to_remove = []
        for symbol, trade in self.active_trades.items():
            try:
                # جلب آخر سعر
                ticker = exchange.fetch_ticker(symbol)
                current_price = ticker['last']
                # التحقق من تحقيق الهدف
                if current_price >= trade['target']:
                    # إغلاق رابح
                    profit = trade['position_value'] * 0.10
                    self.balance += trade['position_value'] + profit
                    # خصم عمولة الخروج
                    self.balance -= (trade['position_value'] + profit) * COMMISSION
                    print(f"🎉 تحقيق الهدف على {symbol} | الربح: {profit:.2f} | الرصيد: {self.balance:.2f}")
                    self.log_close(symbol, 'WIN', 10.0)
                    symbols_to_remove.append(symbol)
                elif current_price <= trade['stop']:
                    # إغلاق خاسر
                    loss = trade['position_value'] * 0.04
                    self.balance += trade['position_value'] - loss
                    self.balance -= (trade['position_value'] - loss) * COMMISSION
                    print(f"⚠️ تفعيل وقف الخسارة على {symbol} | الخسارة: {loss:.2f} | الرصيد: {self.balance:.2f}")
                    self.log_close(symbol, 'LOSS', -4.0)
                    symbols_to_remove.append(symbol)
                else:
                    # التحقق من انقضاء 24 ساعة (86400 ثانية)
                    if time.time() - trade['entry_time'] > 86400:
                        # إغلاق تلقائي بسعر السوق
                        pct_change = (current_price - trade['entry_price']) / trade['entry_price']
                        pnl = trade['position_value'] * pct_change
                        self.balance += trade['position_value'] + pnl
                        self.balance -= (trade['position_value'] + pnl) * COMMISSION
                        print(f"⏰ إغلاق تلقائي لـ {symbol} بعد 24 ساعة | التغير: {pct_change*100:.2f}%")
                        self.log_close(symbol, 'TIMEOUT', pct_change*100)
                        symbols_to_remove.append(symbol)
            except Exception as e:
                print(f"خطأ في تحديث صفقة {symbol}: {e}")

        # إزالة الصفقات المنتهية
        for sym in symbols_to_remove:
            del self.active_trades[sym]

    def log_close(self, symbol, status, pct):
        """تسجيل إغلاق الصفقة في ملف CSV"""
        try:
            df = pd.read_csv(CSV_FILE)
            # نعدل آخر صفقة مفتوحة لهذا الرمز (أبسط طريقة)
            mask = (df['Symbol'] == symbol) & (df['Status'] == 'OPEN')
            if mask.any():
                idx = df[mask].index[-1]
                df.loc[idx, 'Status'] = status
                df.loc[idx, 'Result_Pct'] = f"{pct:.2f}%"
                df.to_csv(CSV_FILE, index=False)
        except Exception as e:
            print(f"خطأ في التسجيل: {e}")

# --- التشغيل ---
if __name__ == "__main__":
    bot = SnowballSniper()

    print("اختر الوضع:")
    print("1: اختبار عكسي (Backtest) لآخر 30 يوم")
    print("2: تداول حي (محاكاة)")
    mode = input("أدخل 1 أو 2: ")

    if mode == "1":
        bot.run_backtest(days=30)
    elif mode == "2":
        bot.run_live()
    else:
        print("مدخل غير صحيح.")
