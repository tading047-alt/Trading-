# main.py - الكود الكامل الذي يعمل
import gspread
from google.oauth2.service_account import Credentials
import telegram
import os
from datetime import datetime

# ============================================
# بياناتك (من ملف JSON الذي أرسلته)
# ============================================

TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
TELEGRAM_CHAT_ID = "5067771509"
SHEET_NAME = "Produits"  # اسم ملف Google Sheet
JSON_KEYFILE = "credentials.json"  # ضع ملف JSON في نفس المجلد بهذا الاسم

# ============================================
# نطاقات الصلاحيات المطلوبة
# ============================================

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# ============================================
# دالة إرسال إلى Telegram
# ============================================

def send_telegram(message):
    """إرسال رسالة إلى Telegram"""
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
        print("✅ تم الإرسال إلى Telegram")
        return True
    except Exception as e:
        print(f"❌ فشل الإرسال إلى Telegram: {e}")
        return False

# ============================================
# دالة الاتصال بجوجل شيت
# ============================================

def connect_to_sheet():
    """الاتصال بجوجل شيت وفتح الملف"""
    try:
        # 1. التحقق من وجود ملف JSON
        if not os.path.exists(JSON_KEYFILE):
            raise Exception(f"❌ ملف {JSON_KEYFILE} غير موجود!")
        
        # 2. إنشاء بيانات الاعتماد
        creds = Credentials.from_service_account_file(JSON_KEYFILE, scopes=SCOPES)
        
        # 3. الاتصال بخدمة جوجل شيت
        client = gspread.authorize(creds)
        print("✅ تم الاتصال بخدمة Google Sheets")
        
        # 4. فتح الملف بالاسم
        spreadsheet = client.open(SHEET_NAME)
        print(f"✅ تم فتح الملف: {spreadsheet.title}")
        
        # 5. فتح أول ورقة
        sheet = spreadsheet.sheet1
        print(f"✅ تم فتح الورقة: {sheet.title}")
        
        return sheet, spreadsheet
        
    except Exception as e:
        print(f"❌ خطأ في الاتصال: {e}")
        return None, None

# ============================================
# الدالة الرئيسية
# ============================================

def main():
    print("=" * 50)
    print("🚀 تشغيل برنامج إشعارات Google Sheets → Telegram")
    print("=" * 50)
    print(f"📅 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📁 ملف JSON: {JSON_KEYFILE}")
    print(f"📊 اسم الشيت: {SHEET_NAME}")
    print("=" * 50)
    
    # إرسال إشعار بدء التشغيل
    send_telegram("🔄 **بدء تشغيل البوت**\nجاري الاتصال بـ Google Drive...")
    
    # 1. الاتصال بجوجل شيت
    sheet, spreadsheet = connect_to_sheet()
    
    if not sheet:
        send_telegram("❌ **فشل الاتصال**\nلم يتم العثور على ملف JSON أو فشل الاتصال.")
        return
    
    # 2. إرسال إشعار نجاح الاتصال
    send_telegram("✅ **تم الاتصال بـ Google Drive بنجاح**")
    
    # 3. إرسال إشعار فتح الملف
    send_telegram(f"✅ **تم فتح Google Sheet بنجاح**\n📄 اسم الملف: {spreadsheet.title}")
    
    # 4. قراءة البيانات
    try:
        all_values = sheet.get_all_values()
        row_count = len(all_values)
        col_count = len(all_values[0]) if row_count > 0 else 0
        
        # 5. إرسال معلومات الملف
        info = f"""
📊 <b>معلومات Google Sheet</b>
─────────────────────
📄 اسم الملف: {spreadsheet.title}
📋 الورقة: {sheet.title}
📏 عدد الصفوف: {row_count}
📐 عدد الأعمدة: {col_count}
📅 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        send_telegram(info)
        
        # 6. إرسال عينة من البيانات
        if row_count > 0:
            sample = "📋 <b>عينة من البيانات (أول 5 صفوف):</b>\n"
            for i in range(min(5, row_count)):
                row = all_values[i]
                sample += f"\n<b>الصف {i+1}:</b> "
                cells = [str(cell)[:25] for cell in row[:4]]
                sample += " | ".join(cells)
                if len(row) > 4:
                    sample += " ..."
            send_telegram(sample)
        
        print(f"\n✨ تم بنجاح!")
        print(f"📊 {row_count} صف × {col_count} عمود")
        print("📱 تحقق من Telegram")
        
    except Exception as e:
        error_msg = f"❌ **خطأ في قراءة البيانات**\n{str(e)}"
        print(error_msg)
        send_telegram(error_msg)

# ============================================
# تشغيل البرنامج
# ============================================

if __name__ == "__main__":
    main()
