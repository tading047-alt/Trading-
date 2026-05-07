import ccxt
import pandas as pd
import requests
import time
import sys

# --- إعدادات التلجرام ---
TELEGRAM_TOKEN = '8603477836:AAGG6Outg3Z9vBI-NjWQ3ALJroh_Cye3l2c'
TELEGRAM_CHAT_ID = '6018153093'

def send_telegram_msg(message):
    print(f">>> محاولة إرسال رسالة تليجرام: {message[:20]}...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"!!! خطأ في إرسال التليجرام: {e}")

# طباعة فورية للتأكد من أن الملف يعمل
print("1. [OK] تم تحميل المكتبات بنجاح.")
sys.stdout.flush() # إجبار البايثون على إظهار الطباعة فوراً

def calculate_rsi(prices, period=14):
    if len(prices) < period: return None
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

print("2. [OK] جاري محاولة إنشاء اتصال مع المنصات...")
sys.stdout.flush()

try:
    exchanges = {
        'Binance': ccxt.binance({'enableRateLimit': True}),
        'Gateio': ccxt.gateio({'enableRateLimit': True})
    }
    print("3. [OK] تم الاتصال المبدئي بالمنصات.")
except Exception as e:
    print(f"!!! فشل الاتصال بالمنصات: {e}")
    sys.exit()

def scan_market():
    print("\n--- بدأت دورة فحص جديدة ---")
    for name, ex in exchanges.items():
        try:
            print(f"🔍 فحص {name}...")
            sys.stdout.flush()
            
            tickers = ex.fetch_tickers()
            print(f"✅ تم جلب {len(tickers)} عملة من {name}.")
            
            for symbol, ticker in tickers.items():
                if '/USDT' in symbol:
                    change = ticker.get('percentage', 0)
                    
                    # اختبار: غيرناه لـ 0.01 لنتأكد أنه يرسل إشعاراً الآن
                    if change >= 0.01: 
                        print(f"🎯 عملة {symbol} صاعدة بنسبة {change:.2f}%")
                        # (باقي الكود الخاص بالـ RSI هنا...)
                        # للتبسيط في الاختبار، سنرسل رسالة مباشرة
                        send_telegram_msg(f"البوت يعمل! وجدنا {symbol} مرتفعة.")
                        return # نخرج بعد أول رسالة للتأكد فقط
        except Exception as e:
            print(f"!!! خطأ في فحص {name}: {e}")

print("4. [START] الكود سيبدأ الحلقة اللانهائية الآن...")
sys.stdout.flush()

while True:
    scan_market()
    print("💤 انتظار 60 ثانية...")
    sys.stdout.flush()
    time.sleep(60)
