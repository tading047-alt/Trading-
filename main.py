import gspread
from google.oauth2.service_account import Credentials
from telegram import Bot
import os
import json
from datetime import datetime

# ============================================
# 🔐 قم بإدخال بياناتك هنا (ملف credentials.json)
# ============================================

# 1. معلومات ملف Google Sheet
# معرف الملف من الرابط:
# https://docs.google.com/spreadsheets/d/163bpUCuaPpOVTMs73y2cBSa6KCOxIXzIWk2NNonOTrs/edit
SHEET_ID = "163bpUCuaPpOVTMs73y2cBSa6KCOxIXzIWk2NNonOTrs"
SHEET_NAME = "Sheet1"  # أو اسم الورقة التي تريدها

# 2. معلومات Telegram (ضعها في متغيرات البيئة - الأكثر أماناً)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "ضع_التوكن_هنا_يدوياً")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "ضع_رقم_الدردشة_هنا")

# 3. مسار ملف JSON من Google Cloud
JSON_KEYFILE = "credentials.json"  # ضع ملف JSON في نفس المجلد

# ============================================
# دوال البرنامج
# ============================================

def connect_to_google_sheet():
    """الاتصال بـ Google Sheets باستخدام ملف JSON"""
    try:
        scope = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # التحقق من وجود ملف JSON
        if not os.path.exists(JSON_KEYFILE):
            raise Exception(f"ملف {JSON_KEYFILE} غير موجود! تأكد من وضعه في نفس المجلد")
        
        # تحميل بيانات الاعتماد
        creds = Credentials.from_service_account_file(JSON_KEYFILE, scopes=scope)
        client = gspread.authorize(creds)
        
        # فتح الملف باستخدام المعرف
        sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
        
        print("✅ تم الاتصال بـ Google Drive بنجاح")
        print("✅ تم فتح Google Sheet بنجاح")
        
        return sheet
        
    except Exception as e:
        print(f"❌ خطأ في الاتصال: {e}")
        return None

def send_telegram_message(message):
    """إرسال رسالة إلى Telegram"""
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
        print("✅ تم إرسال الإشعار إلى Telegram")
        return True
    except Exception as e:
        print(f"❌ خطأ في إرسال رسالة Telegram: {e}")
        return False

def read_first_rows(sheet, num_rows=5):
    """قراءة أول عدد محدد من الصفوف"""
    try:
        rows = sheet.get_all_values()
        if not rows:
            return None
        
        print(f"📊 تم قراءة {len(rows)} صف و {len(rows[0])} عمود")
        return rows[:num_rows]
        
    except Exception as e:
        print(f"❌ خطأ في قراءة البيانات: {e}")
        return None

def format_telegram_message(data):
    """تنسيق البيانات لإرسالها إلى Telegram"""
    if not data:
        return "⚠️ لا توجد بيانات في Google Sheet"
    
    message = "📊 <b>بيانات Google Sheet</b>\n\n"
    message += f"📅 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    message += f"🆔 معرف الملف: {SHEET_ID}\n"
    message += "─" * 20 + "\n\n"
    
    for i, row in enumerate(data):
        message += f"<b>الصف {i+1}:</b>\n"
        for j, cell in enumerate(row):
            message += f"  {chr(65+j)}: {cell}\n"
        message += "\n"
    
    # Telegram limit is ~4096 characters
    if len(message) > 4000:
        message = message[:4000] + "\n\n... (تم اقتطاع الرسالة)"
    
    return message

# ============================================
# الدالة الرئيسية
# ============================================

def main():
    """الدالة الرئيسية للتشغيل"""
    print("🔄 بدء تشغيل البرنامج...")
    
    # 1. الاتصال بـ Google Sheet
    sheet = connect_to_google_sheet()
    
    if not sheet:
        send_telegram_message("❌ فشل الاتصال بـ Google Drive أو فتح Google Sheet")
        return
    
    # 2. إرسال إشعار نجاح الاتصال
    success_message = "✅ تم الاتصال بـ Google Drive بنجاح\n✅ تم فتح Google Sheet بنجاح"
    send_telegram_message(success_message)
    
    # 3. قراءة البيانات (اختياري - قم بإزالة التعليق إذا أردت إرسال البيانات)
    """
    print("🔄 جاري قراءة البيانات...")
    data = read_first_rows(sheet, num_rows=5)
    
    if data:
        formatted_message = format_telegram_message(data)
        send_telegram_message(formatted_message)
    else:
        send_telegram_message("⚠️ لا توجد بيانات للعرض في Google Sheet")
    """
    
    print("\n✅ تم الانتهاء بنجاح!")

# ============================================
# تشغيل البرنامج
# ============================================

if __name__ == "__main__":
    main()
