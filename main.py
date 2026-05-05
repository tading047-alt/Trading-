# main_corrected.py
import gspread
import telegram
import os
from datetime import datetime

# ============================================
# بياناتك - تم تصحيح اسم الملف
# ============================================

TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
TELEGRAM_CHAT_ID = "5067771509"
FILE_NAME = "Produits"  # ✅ اسم الملف الصحيح
JSON_KEYFILE = "credentials.json"

def send_telegram(message):
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
        print("✅ تم الإرسال")
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")

def main():
    print("=" * 50)
    print("🚀 تشغيل برنامج الإشعارات")
    print("=" * 50)
    
    try:
        # 1. الاتصال بـ Google Drive
        print("🔄 جاري الاتصال بـ Google Drive...")
        send_telegram("🔄 جاري الاتصال بـ Google Drive...")
        
        client = gspread.service_account(filename=JSON_KEYFILE)
        
        send_telegram("✅ تم الاتصال بـ Google Drive بنجاح")
        print("✅ تم الاتصال بـ Google Drive")
        
        # 2. فتح الملف بالاسم (بدون ID)
        print(f"🔄 جاري فتح ملف '{FILE_NAME}'...")
        send_telegram(f"🔄 جاري فتح ملف '{FILE_NAME}'...")
        
        # فتح الملف باستخدام الاسم
        spreadsheet = client.open(FILE_NAME)
        sheet = spreadsheet.sheet1
        
        send_telegram("✅ تم فتح Google Sheet بنجاح")
        print(f"✅ تم فتح الملف: {spreadsheet.title}")
        print(f"✅ الورقة: {sheet.title}")
        
        # 3. قراءة البيانات
        all_values = sheet.get_all_values()
        row_count = len(all_values)
        col_count = len(all_values[0]) if row_count > 0 else 0
        
        # 4. إرسال معلومات الملف
        info_message = f"""
📊 <b>معلومات Google Sheet</b>
─────────────────────
📄 اسم الملف: {spreadsheet.title}
📋 اسم الورقة: {sheet.title}
📏 عدد الصفوف: {row_count}
📐 عدد الأعمدة: {col_count}
📅 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        send_telegram(info_message)
        
        # 5. إرسال عينة من البيانات
        if row_count > 0:
            sample = "📋 <b>عينة من البيانات (أول 5 صفوف):</b>\n"
            for i in range(min(5, row_count)):
                row = all_values[i]
                sample += f"\n<b>الصف {i+1}:</b> "
                cells = [str(cell)[:20] for cell in row[:4]]
                sample += " | ".join(cells)
                if len(row) > 4:
                    sample += " ..."
            send_telegram(sample)
        
        print(f"\n✨ تم بنجاح!")
        print(f"📊 {row_count} صف × {col_count} عمود")
        print("📱 تحقق من Telegram")
        
    except gspread.exceptions.SpreadsheetNotFound:
        error_msg = f"❌ لم يتم العثور على ملف باسم '{FILE_NAME}'!"
        print(error_msg)
        send_telegram(error_msg)
        send_telegram("💡 تأكد من مشاركة الملف مع حساب الخدمة")
        
    except Exception as e:
        error_msg = f"❌ خطأ: {str(e)}"
        print(error_msg)
        send_telegram(error_msg)

if __name__ == "__main__":
    main()
