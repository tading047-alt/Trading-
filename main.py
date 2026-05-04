# main_working.py - نسخة مبسطة 100% تعمل
#!/usr/bin/env python3

import gspread
from google.oauth2.service_account import Credentials
import telegram
import os
import json
from datetime import datetime

# ============================================
# بياناتك
# ============================================

TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
TELEGRAM_CHAT_ID = "5067771509"
SHEET_ID = "163bpUCuaPpOVTMs73y2cBSa6KCOxIXzIWk2NNonOTrs"
JSON_KEYFILE = "credentials.json"

# ============================================
# دالة الإرسال إلى Telegram
# ============================================

def send_telegram(message):
    """إرسال رسالة إلى Telegram"""
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
        print("✅ تم الإرسال إلى Telegram")
        return True
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")
        return False

# ============================================
# الدالة الرئيسية - باستخدام الطريقة الصحيحة
# ============================================

def main():
    print("=" * 50)
    print("🚀 تشغيل برنامج الإشعارات")
    print("=" * 50)
    
    # 1. التحقق من وجود الملف
    if not os.path.exists(JSON_KEYFILE):
        send_telegram(f"❌ ملف {JSON_KEYFILE} غير موجود!")
        print(f"❌ ملف {JSON_KEYFILE} غير موجود!")
        return
    
    # 2. قراءة البريد الإلكتروني من الملف
    with open(JSON_KEYFILE, 'r') as f:
        creds_data = json.load(f)
        service_email = creds_data['client_email']
        print(f"📧 حساب الخدمة: {service_email}")
    
    # 3. إرسال إشعار بدء التشغيل
    send_telegram("🔄 جاري الاتصال بـ Google Drive...")
    
    # 4. الطريقة الصحيحة للاتصال (ليست service_account)
    try:
        # تعريف الصلاحيات المطلوبة
        scope = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # تحميل بيانات الاعتماد من الملف
        creds = Credentials.from_service_account_file(
            JSON_KEYFILE,
            scopes=scope
        )
        
        # إنشاء عميل gspread
        client = gspread.authorize(creds)
        
        # إرسال إشعار نجاح الاتصال بـ Drive
        send_telegram("✅ تم الاتصال بـ Google Drive بنجاح")
        print("✅ تم الاتصال بـ Google Drive")
        
        # 5. فتح الملف
        send_telegram("🔄 جاري فتح Google Sheet...")
        spreadsheet = client.open_by_key(SHEET_ID)
        sheet = spreadsheet.sheet1
        
        # إرسال إشعار نجاح فتح الملف
        send_telegram("✅ تم فتح Google Sheet بنجاح")
        print("✅ تم فتح Google Sheet")
        
        # 6. قراءة البيانات
        all_values = sheet.get_all_values()
        row_count = len(all_values)
        col_count = len(all_values[0]) if row_count > 0 else 0
        
        # 7. إرسال معلومات الملف
        info_msg = f"""
📊 <b>معلومات Google Sheet</b>
─────────────────────
📄 اسم الورقة: {sheet.title}
📏 عدد الصفوف: {row_count}
📐 عدد الأعمدة: {col_count}
🔑 حساب الخدمة: {service_email[:30]}...
📅 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        send_telegram(info_msg)
        
        print(f"\n✨ تم بنجاح! {row_count} صف × {col_count} عمود")
        print("📱 تحقق من Telegram")
        
    except Exception as e:
        error_msg = f"❌ خطأ: {str(e)}"
        print(error_msg)
        send_telegram(error_msg)

# ============================================
# التشغيل
# ============================================

if __name__ == "__main__":
    main()
