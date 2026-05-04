import gspread
from google.oauth2.service_account import Credentials
from telegram import Bot
import os
import logging
import sys

# --- التهيئة والإعدادات --------------------------------
# 🔐 بيانات الاعتماد (تم إدخالها مباشرة كما طلبت)
TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
TELEGRAM_CHAT_ID = "5067771509"

# 🗂️ تم استخراج معرف الملف (Sheet ID) من الرابط:
# https://docs.google.com/spreadsheets/d/163bpUCuaPpOVTMs73y2cBSa6KCOxIXzIWk2NNonOTrs/edit?usp=drivesdk
GOOGLE_SHEET_ID = "163bpUCuaPpOVTMs73y2cBSa6KCOxIXzIWk2NNonOTrs"

# --- إعداد نظام تسجيل الأحداث (Logging) ---------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 1. الاتصال بـ Google Sheets -----------------------
def connect_to_google_sheet(json_keyfile_path='credentials.json'):
    """
    الاتصال بـ Google Sheets باستخدام ملف JSON لحساب الخدمة.
    يفترض أن ملف credentials.json موجود في نفس المجلد.
    """
    try:
        # نطاقات الوصول المطلوبة
        scope = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive.readonly' # نطاق أقل صلاحية للقراءة فقط
        ]
        
        # تحميل بيانات الاعتماد من ملف JSON
        creds = None
        if not os.path.exists(json_keyfile_path):
            raise FileNotFoundError(f"الملف {json_keyfile_path} غير موجود في المسار الحالي.")
        
        creds = Credentials.from_service_account_file(json_keyfile_path, scopes=scope)
        client = gspread.authorize(creds)
        
        # فتح Google Sheet باستخدام المعرف (ID)
        sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1
        
        logger.info("✅ تم الاتصال بـ Google Drive وفتح Google Sheet بنجاح")
        return sheet
        
    except FileNotFoundError as e:
        logger.error(f"❌ فشل الاتصال بالـ Drive: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ فشل الاتصال أو الفتح: {e}", exc_info=True)
        return None

# --- 2. إرسال إشعار إلى Telegram -----------------------
def send_telegram_message(message):
    """إرسال رسالة نصية إلى قناة Telegram المحددة."""
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        # استخدام parse_mode='HTML' لتنسيق النص لو أردت
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
        logger.info("✅ تم إرسال الإشعار إلى Telegram بنجاح")
        return True
    except Exception as e:
        logger.error(f"❌ فشل إرسال رسالة إلى Telegram: {e}")
        return False

# --- 3. الدالة الرئيسية (التنفيذ الكامل) -----------------
def main():
    """الدالة الرئيسية التي تنفذ كل الخطوات بشكل متسلسل."""
    logger.info("🚀 بدء تشغيل سكريبت الاتصال بـ Google Sheets وإرسال الإشعارات...")
    
    # الخطوة 1: إرسال إشعار بدء المحاولة (اختياري)
    send_telegram_message("🔄 جاري الاتصال بـ Google Drive وفتح الملف...")
    
    # الخطوة 2: الاتصال بـ Google Sheets باستخدام ملف JSON (مطلوب)
    # تأكد أن ملف credentials.json موجود في نفس مسار هذا السكريبت
    sheet = connect_to_google_sheet(json_keyfile_path='credentials.json')
    
    # الخطوة 3: بناء رسالة النتيجة وإرسالها إلى Telegram
    if sheet:
        # نجاح الاتصال والفتح
        success_message = (
            "✅ <b>تم الاتصال بـ Google Drive بنجاح</b>\n"
            "✅ <b>تم فتح Google Sheet بنجاح</b>\n\n"
            f"📊 <b>اسم الورقة:</b> {sheet.title}\n"
            f"🔢 <b>عدد الصفوف:</b> {len(sheet.get_all_values()) if sheet.get_all_values() else 0}"
        )
        send_telegram_message(success_message)
    else:
        # فشل في إحدى الخطوتين
        error_message = (
            "❌ <b>فشل في الاتصال بـ Google Drive أو فتح الملف</b>\n"
            "يرجى التحقق من:\n"
            "• وجود ملف credentials.json في المسار الصحيح\n"
            "• مشاركة ملف Google Sheet مع بريد حساب الخدمة\n"
            "• صحة معرف الملف (Sheet ID) في الكود"
        )
        send_telegram_message(error_message)
    
    logger.info("🏁 انتهاء تنفيذ السكريبت.\n" + "-"*40)

# --- 4. نقطة دخول البرنامج --------------------------------
if __name__ == "__main__":
    main()
