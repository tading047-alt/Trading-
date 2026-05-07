import ccxt
import pandas as pd
import requests
import time

# --- إعدادات التلجرام ---
TELEGRAM_TOKEN = '8603477836:AAGG6Outg3Z9vBI-NjWQ3ALJroh_Cye3l2c'
TELEGRAM_CHAT_ID = '5067771509'

def send_telegram_msg(message):
    print(f"📤 محاولة إرسال رسالة لتليجرام...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        r = requests.post(url, json=payload)
        if r.status_id == 200:
            print("✅ تم إرسال رسالة التليجرام بنجاح.")
        else:
            print(f"❌ فشل إرسال التليجرام. الكود: {r.status_code}, الرد: {r.text}")
    except Exception as e:
        print(f"❌ خطأ فني في إرسال التليجرام: {e}")

def calculate_rsi(prices, period=14):
    try:
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    except Exception as e:
        print(f"❌ خطأ في عملية حساب RSI: {e}")
        return None

# إعداد المنصات
print("⚙️ جاري الاتصال بالمنصات (Binance & Gateio)...")
exchanges = {'Binance': ccxt.binance(), 'Gateio': ccxt.gateio()}

def get_market_data(ex_obj, symbol):
    try:
        print(f"📊 جاري سحب بيانات الشموع لعملة {symbol}...")
        bars = ex_obj.fetch_ohlcv(symbol, timeframe='5m', limit=50)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
        rsi_series = calculate_rsi(df['close'])
        val = rsi_series.iloc[-1]
        print(f"🔎 النتيجة: {symbol} | RSI: {val:.2f}")
        return val
    except Exception as e:
        print(f"⚠️ تعذر جلب RSI لعملة {symbol}: {e}")
        return None

def scan_market():
    for name, ex in exchanges.items():
        print(f"\n--- 🔎 فحص منصة {name} الآن ---")
        try:
            print(f"🌐 جاري جلب أسعار جميع العملات من {name}...")
            tickers = ex.fetch_tickers()
            print(f"✅ تم جلب {len(tickers)} عملة من {name}.")
            
            found_high_change = 0
            for symbol, ticker in tickers.items():
                if '/USDT' in symbol or ':USDT' in symbol:
                    change = ticker.get('percentage', 0)
                    
                    # ملاحظة: إذا أردت الاختبار، غير الـ 50 إلى 0.1 هنا
                    if change >= 50:
                        found_high_change += 1
                        print(f"🎯 وجدنا عملة صاعدة! {symbol} بنسبة {change:.2f}%")
                        rsi_val = get_market_data(ex, symbol)
                        
                        if rsi_val and rsi_val >= 80:
                            last_price = ticker.get('last', 0)
                            msg = (
                                f"🚨 *فرصة شورت!*\n"
                                f"🏛 المنصة: `{name}`\n"
                                f"💰 العملة: `{symbol}`\n"
                                f"📈 الارتفاع: `{change:.2f}%`\n"
                                f"🔥 RSI: `{rsi_val:.2f}`"
                            )
                            send_telegram_msg(msg)
            
            if found_high_change == 0:
                print(f"ℹ️ لا توجد عملات مرتفعة فوق 50% حالياً في {name}.")

        except Exception as e:
            print(f"❌ خطأ كبير أثناء فحص {name}: {e}")

print("🚀 تشغيل الرادار... (اضغط Ctrl+C للإيقاف)")
while True:
    scan_market()
    print("\n💤 انتهى الفحص. انتظار 3 دقائق...")
    time.sleep(180)
