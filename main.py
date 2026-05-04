import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from telegram.ext import Application, CommandHandler

# --- الإعدادات الخاصة بك (نفس البيانات السابقة) ---
SERVICE_ACCOUNT_FILE = 'credentials.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
MY_FILE_ID = "163bpUCuaPpOVTMs73y2cBSa6KCOxIXzIWk2NNonOTrs"
MY_CHAT_ID = "5067771509"

# الاتصال بجوجل درايف
def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

# وظيفة تحليل البيانات وإرسال التقرير مع الإشعارات المطلوبة
async def send_report(update, context):
    chat_id = update.effective_chat.id
    
    # التأكد من هوية المستخدم
    if str(chat_id) != MY_CHAT_ID:
        await update.message.reply_text("عذراً، لا تملك صلاحية الوصول.")
        return

    try:
        # البدء بالاتصال
        service = get_drive_service()
        
        # محاولة الوصول للملف للتأكد من الربط
        file_metadata = service.files().get(fileId=MY_FILE_ID).execute()
        
        # --- الإشعار الذي طلبته عند نجاح الاتصال ---
        if file_metadata:
            await context.bot.send_message(
                chat_id=chat_id, 
                text="✅ تم الاتصال بـ قوقلدريف و ربط ملف google sheet بنجاح"
            )

        # متابعة العمل (تحميل الملف)
        request = service.files().get_media(fileId=MY_FILE_ID)
        file_stream = io.BytesIO()
        downloader = MediaIoBaseDownload(file_stream, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        file_stream.seek(0)
        
        # إرسال الملف الأصلي كإشعار إضافي
        await context.bot.send_document(
            chat_id=chat_id, 
            document=file_stream, 
            filename="database_update.xlsx",
            caption="📂 نسخة من البيانات المستلمة."
        )

    except Exception as e:
        await update.message.reply_text(f"❌ فشل الاتصال: تأكد من مشاركة الملف مع حساب الخدمة.\nالخطأ: {str(e)}")

if __name__ == '__main__':
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("report", send_report))
    print("🚀 البوت يعمل الآن.. بانتظار أمر /report")
    app.run_polling()
