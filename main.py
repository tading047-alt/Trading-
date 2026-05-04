import io
import pandas as pd
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from telegram.ext import Application, CommandHandler

# إعداد السجلات لمراقبة أداء البوت على Railway
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- الإعدادات الخاصة بك التي قدمتها ---
SERVICE_ACCOUNT_FILE = 'credentials.json' # تأكد من وجود هذا الملف بجانب الكود
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
MY_FILE_ID = "163bpUCuaPpOVTMs73y2cBSa6KCOxIXzIWk2NNonOTrs"
MY_CHAT_ID = "5067771509"
SHEET_NAME = "sheet1"

# دالة الاتصال بـ Google Drive
def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

# الدالة الأساسية للربط وإرسال الإشعار
async def check_connection(update, context):
    chat_id = update.effective_chat.id
    
    # حماية للوصول الخاص بك فقط
    if str(chat_id) != MY_CHAT_ID:
        await update.message.reply_text("🚫 لا تملك صلاحية الوصول.")
        return

    try:
        # 1. محاولة الاتصال بجوجل درايف
        service = get_drive_service()
        
        # 2. جلب معلومات الملف للتأكد من نجاح الربط
        file_metadata = service.files().get(fileId=MY_FILE_ID).execute()
        
        # 3. إرسال الإشعار المطلوب فوراً
        await context.bot.send_message(
            chat_id=chat_id, 
            text="✅ تم الاتصال بـ قوقلدريف و ربط ملف google sheet بنجاح"
        )

        # 4. محاولة قراءة البيانات للتأكد من صلاحية الوصول لـ sheet1
        request = service.files().get_media(fileId=MY_FILE_ID)
        file_stream = io.BytesIO()
        downloader = MediaIoBaseDownload(file_stream, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        
        file_stream.seek(0)
        # قراءة ورقة العمل المحددة (sheet1)
        df = pd.read_excel(file_stream, sheet_name=SHEET_NAME)
        
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"📊 تم الدخول إلى ورقة العمل ({SHEET_NAME}) بنجاح.\nعدد الأسطر المكتشفة: {len(df)}"
        )

    except Exception as e:
        await update.message.reply_text(f"❌ فشل الاتصال: {str(e)}\nتأكد من مشاركة الملف مع إيميل حساب الخدمة.")

async def start(update, context):
    await update.message.reply_text("🤖 بوت الأتمتة جاهز.\nاستخدم /check لاختبار ربط Google Sheet.")

if __name__ == '__main__':
    # بناء التطبيق مع خاصية تنظيف التحديثات المعلقة لحل مشكلة الـ Conflict
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_connection))
    
    print("🚀 البوت يعمل الآن.. بانتظار أمر /check")
    application.run_polling(drop_pending_updates=True)
