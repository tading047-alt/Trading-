# main.py - النسخة النهائية التي تعمل
import requests
import time
from datetime import datetime

# ======================== إعدادات Telegram ========================
# ⚠️ استخدم التوكن الجديد الذي حصلت عليه من @BotFather بعد إبطال القديم
TELEGRAM_TOKEN = "8628541851:AAGTo4LDtxv8WOy40L5YI7kqIdwv2SLNUKI"
TELEGRAM_CHAT_ID = "5067771509"

# ======================== دوال Telegram ========================

def send_telegram_message(text):
    """إرسال رسالة إلى Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        result = response.json()
        
        if result.get("ok"):
            print(f"✅ {datetime.now().strftime('%H:%M:%S')} - تم الإرسال")
            return True
        else:
            print(f"❌ فشل: {result}")
            return False
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return False

# ======================== دوال Gate.io ========================

def get_gateio_tickers():
    """جلب جميع العملات من Gate.io"""
    try:
        url = "https://data.gateapi.io/api2/1/tickers"
        response = requests.get(url, timeout=30)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"⚠️ خطأ API: {response.status_code}")
            return None
    except Exception as e:
        print(f"⚠️ خطأ في الاتصال: {e}")
        return None

def find_high_gainers(tickers, min_gain=100):
    """البحث عن العملات المرتفعة أكثر من min_gain%"""
    gainers = []
    
    if not tickers:
        return gainers
    
    for symbol, data in tickers.items():
        try:
            # تخطي العملات التي لا تحتوي على USDT
            if not symbol.endswith('_usdt'):
                continue
            
            percent_change = float(data.get('percentChange', 0))
            
            if percent_change > min_gain:
                gainers.append({
                    'symbol': symbol.upper().replace('_USDT', ''),
                    'percent': percent_change,
                    'price': float(data.get('last', 0)),
                    'high': float(data.get('high24hr', 0)),
                    'low': float(data.get('low24hr', 0)),
                    'volume': float(data.get('baseVolume', 0))
                })
        except Exception as e:
            continue
    
    # ترتيب تنازلي حسب النسبة
    gainers.sort(key=lambda x: x['percent'], reverse=True)
    return gainers

# ======================== الدالة الرئيسية ========================

def main():
    print("=" * 50)
    print("🚀 بوت مراقبة Gate.io - العملات المرتفعة أكثر من 100%")
    print("=" * 50)
    
    # اختبار الاتصال بـ Telegram أولاً
    print("\n📡 اختبار الاتصال بـ Telegram...")
    if not send_telegram_message("🤖 <b>البوت يعمل الآن!</b>\n✅ جاري مراقبة Gate.io..."):
        print("❌ فشل الاتصال بـ Telegram! تأكد من التوكن ورقم الدردشة")
        return
    
    print("✅ الاتصال بـ Telegram ناجح")
    print("🔍 بدء مراقبة Gate.io...\n")
    
    while True:
        try:
            now = datetime.now()
            print(f"\n{'='*40}")
            print(f"🔄 {now.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*40}")
            
            # جلب البيانات
            print("📡 جلب بيانات Gate.io...")
            tickers = get_gateio_tickers()
            
            if tickers:
                print(f"✅ تم جلب بيانات {len(tickers)} عملة")
                
                # البحث عن العملات المرتفعة
                gainers = find_high_gainers(tickers, min_gain=100)
                
                if gainers:
                    print(f"\n🎯 تم العثور على {len(gainers)} عملة مرتفعة أكثر من 100%!")
                    
                    # عرض في الطرفية
                    for coin in gainers[:10]:
                        print(f"   📈 {coin['symbol']}: +{coin['percent']:.2f}%")
                    
                    # بناء رسالة Telegram
                    message = f"""
🚀 <b>عملات مرتفعة أكثر من 100% على Gate.io</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 {now.strftime('%Y-%m-%d %H:%M:%S')}
📊 عدد العملات: {len(gainers)}
━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
                    
                    for i, coin in enumerate(gainers[:15], 1):
                        message += f"""
<b>{i}. {coin['symbol']}</b>
📈 <b>+{coin['percent']:.2f}%</b>
💰 {coin['price']:.8f} USDT
📊 أعلى: {coin['high']:.8f}
📉 أدنى: {coin['low']:.8f}
─────────────────
"""
                    
                    message += f"\n✅ آخر تحديث: {now.strftime('%H:%M:%S')}"
                    
                    # إرسال إلى Telegram
                    send_telegram_message(message)
                else:
                    print("ℹ️ لا توجد عملات مرتفعة أكثر من 100% حالياً")
                    send_telegram_message(f"📊 <b>تحديث Gate.io</b>\n{now.strftime('%H:%M:%S')}\nℹ️ لا توجد عملات مرتفعة أكثر من 100%")
            else:
                print("❌ فشل جلب البيانات من Gate.io")
            
            # انتظار 5 دقائق
            print("\n⏰ انتظار 5 دقائق...")
            time.sleep(300)
            
        except KeyboardInterrupt:
            print("\n⏹️ تم إيقاف البوت")
            send_telegram_message("⏹️ <b>تم إيقاف بوت المراقبة</b>")
            break
        except Exception as e:
            print(f"❌ خطأ غير متوقع: {e}")
            time.sleep(60)

# ======================== التشغيل ========================
if __name__ == "__main__":
    main()
