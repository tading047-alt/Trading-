# main_fixed.py
import gspread
from google.oauth2.service_account import Credentials
import telegram
import os
from datetime import datetime

# ============================================
# بياناتك
# ============================================

TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
TELEGRAM_CHAT_ID = "5067771509"
FILE_ID = "1RAWDvovHZZ7mEj9A0soo2XnPOudVadxu8KuZeQaR-dM"  # استخدم ID بدلاً من الاسم
JSON_KEYFILE = "credentials.json"

# نطاقات الصلاحيات الموسعة
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/drive.file'
]

def send_telegram(message):
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
        print("✅ تم الإرسال")
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")

def main():
    print("=" * 50)
    print("🚀 تشغيل البرنامج")
    print("=" * 50)
    
    try:
        # 1. الاتصال
        creds = Credentials.from_service_account_file(JSON_KEYFILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        send_telegram("✅ تم الاتصال بـ Google Drive بنجاح")
        
        # 2. فتح الملف باستخدام ID
        spreadsheet = client.open_by_key(FILE_ID)
        sheet = spreadsheet.sheet1
        
        send_telegram("✅ تم فتح Google Sheet بنجاح")
        
        # 3. قراءة البيانات
        all_values = sheet.get_all_values()
        rows = len(all_values)
        cols = len(all_values[0]) if rows > 0 else 0
        
        # 4. إرسال المعلومات
        info = f"""
📊 <b>معلومات Google Sheet</b>
─────────────────────
📄 اسم الملف: {spreadsheet.title}
📋 الورقة: {sheet.title}
📏 الصفوف: {rows}
📐 الأعمدة: {cols}
📅 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        send_telegram(info)
        
        print(f"\n✅ تم بنجاح! {rows} صف × {cols} عمود")
        
    except Exception as e:
        error_msg = f"❌ خطأ: {str(e)}"
        print(error_msg)
        send_telegram(error_msg)

if __name__ == "__main__":
    main()
