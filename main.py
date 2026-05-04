# main.py
import gspread
import telegram
import os
from datetime import datetime

# ============================================
# بياناتك - تم تحديثها بالكامل
# ============================================

TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
TELEGRAM_CHAT_ID = "5067771509"
FILE_ID = "1RAWDvovHZZ7mEj9A0soo2XnPOudVadxu8KuZeQaR-dM"
SHEET_NAME = "sheet1"
JSON_KEYFILE = "credentials.json"

# ============================================
# دالة الإرسال إلى Telegram
# ============================================

def send_telegram(message):
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
        print("✅ تم الإرسال إلى Telegram")
        return True
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")
        return False

# ============================================
# الدالة الرئيسية
# ============================================

def main():
    print("=" * 50)
    print("🚀 تشغيل برنامج الإشعارات")
    print("=" * 50)
    
    # التحقق من وجود ملف JSON
    if not os.path.exists(JSON_KEYFILE):
        send_telegram(f"❌ ملف {JSON_KEYFILE} غير موجود!")
        print(f"❌ ملف {JSON_KEYFILE} غير موجود!")
        return
    
    try:
        # 1. الاتصال بـ Google Drive
        print("🔄 جاري الاتصال بـ Google Drive...")
        send_telegram("🔄 جاري الاتصال بـ Google Drive...")
        
        client = gspread.service_account(filename=JSON_KEYFILE)
        
        send_telegram("✅ تم الاتصال بـ Google Drive بنجاح")
        print("✅ تم الاتصال بـ Google Drive")
        
        # 2. فتح ملف Google Sheet
        print("🔄 جاري فتح Google Sheet...")
        send_telegram("🔄 جاري فتح Google Sheet...")
        
        spreadsheet = client.open_by_key(FILE_ID)
        
        # فتح الورقة المحددة
        try:
            sheet = spreadsheet.worksheet(SHEET_NAME)
        except:
            sheet = spreadsheet.sheet1
            print(f"⚠️ تم استخدام أول ورقة: {sheet.title}")
        
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
🆔 معرف الملف: {FILE_ID[:15]}...
📅 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        send_telegram(info_message)
        
        # 5. إرسال عينة من البيانات (إذا وجدت)
        if row_count > 0:
            sample = "📋 <b>عينة من البيانات (أول 3 صفوف):</b>\n"
            for i in range(min(3, row_count)):
                row = all_values[i]
                sample += f"\n<b>الصف {i+1}:</b> "
                cells = [str(cell)[:20] for cell in row[:3]]
                sample += " | ".join(cells)
                if len(row) > 3:
                    sample += " ..."
            send_telegram(sample)
        
        print(f"\n✨ تم بنجاح!")
        print(f"📊 {row_count} صف × {col_count} عمود")
        print("📱 تحقق من Telegram")
        
    except Exception as e:
        error_msg = f"❌ خطأ: {str(e)}"
        print(error_msg)
        send_telegram(error_msg)

# ============================================
# تشغيل البرنامج
# ============================================

if __name__ == "__main__":
    main()
