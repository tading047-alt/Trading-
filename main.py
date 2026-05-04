# main.py - نسخة مع التحقق من الوقت
import gspread
import telegram
import os
import json
from datetime import datetime

# ============================================
# بياناتك
# ============================================

TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
TELEGRAM_CHAT_ID = "5067771509"
FILE_ID = "1RAWDvovHZZ7mEj9A0soo2XnPOudVadxu8KuZeQaR-dM"
JSON_KEYFILE = "credentials.json"

# ============================================
# دالة الإرسال
# ============================================

def send_telegram(message):
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
        print("✅ تم الإرسال")
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")

# ============================================
# الدالة الرئيسية
# ============================================

def main():
    print("=" * 50)
    print("🚀 تشغيل البرنامج")
    print("=" * 50)
    
    # التحقق من الوقت الحالي
    now = datetime.now()
    print(f"📅 الوقت الحالي: {now}")
    print(f"⚠️ تأكد من أن الوقت صحيح! (يجب أن يكون قريباً من الوقت الحقيقي)")
    
    if now.year < 2024:
        send_telegram(f"⚠️ خطأ في الوقت: {now}. يرجى مزامنة الوقت!")
        print("❌ الوقت غير صحيح!")
        return
    
    # التحقق من ملف JSON
    if not os.path.exists(JSON_KEYFILE):
        send_telegram(f"❌ ملف {JSON_KEYFILE} غير موجود!")
        print(f"❌ ملف {JSON_KEYFILE} غير موجود!")
        return
    
    # قراءة البريد من JSON
    with open(JSON_KEYFILE, 'r') as f:
        data = json.load(f)
        print(f"📧 حساب الخدمة: {data['client_email']}")
    
    send_telegram("🔄 جاري الاتصال بـ Google Drive...")
    
    try:
        # محاولة الاتصال بطرق مختلفة
        
        # الطريقة 1: service_account (الأحدث)
        try:
            client = gspread.service_account(filename=JSON_KEYFILE)
            print("✅ الطريقة 1 نجحت")
        except Exception as e1:
            print(f"⚠️ الطريقة 1 فشلت: {e1}")
            
            # الطريقة 2: مع تحديد الصلاحيات
            try:
                from google.oauth2.service_account import Credentials
                scope = ['https://www.googleapis.com/auth/spreadsheets', 
                        'https://www.googleapis.com/auth/drive']
                creds = Credentials.from_service_account_file(JSON_KEYFILE, scopes=scope)
                client = gspread.authorize(creds)
                print("✅ الطريقة 2 نجحت")
            except Exception as e2:
                raise Exception(f"جميع طرق الاتصال فشلت: {e1}, {e2}")
        
        send_telegram("✅ تم الاتصال بـ Google Drive بنجاح")
        
        # فتح الملف
        print("🔄 جاري فتح الملف...")
        spreadsheet = client.open_by_key(FILE_ID)
        sheet = spreadsheet.sheet1
        
        send_telegram("✅ تم فتح Google Sheet بنجاح")
        
        # قراءة البيانات
        all_values = sheet.get_all_values()
        rows = len(all_values)
        cols = len(all_values[0]) if rows > 0 else 0
        
        info = f"""
📊 <b>معلومات Google Sheet</b>
─────────────────────
📄 اسم الملف: {spreadsheet.title}
📋 الورقة: {sheet.title}
📏 الصفوف: {rows}
📐 الأعمدة: {cols}
📅 الوقت: {now.strftime('%Y-%m-%d %H:%M:%S')}
        """
        send_telegram(info)
        
        print(f"\n✅ تم بنجاح! {rows} صف × {cols} عمود")
        print("📱 تحقق من Telegram")
        
    except Exception as e:
        error_msg = f"❌ خطأ: {str(e)}"
        print(error_msg)
        send_telegram(error_msg)

if __name__ == "__main__":
    main()
