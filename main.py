import io
import pandas as pd
import matplotlib.pyplot as plt
import dataframe_image as dfi
from PIL import Image
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from telegram.ext import Application, CommandHandler
import arabic_reshaper
from bidi.algorithm import get_display

# --- الإعدادات الخاصة بك ---
SERVICE_ACCOUNT_FILE = 'credentials.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
MY_FILE_ID = "163bpUCuaPpOVTMs73y2cBSa6KCOxIXzIWk2NNonOTrs"
MY_CHAT_ID = "5067771509"

# دالة معالجة النصوص العربية
def ar_text(text):
    if not isinstance(text, str): text = str(text)
    return get_display(arabic_reshaper.reshape(text))

# الاتصال بجوجل درايف
def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

# وظيفة تحليل البيانات وإرسال التقرير
async def send_report(update, context):
    chat_id = update.effective_chat.id
    # التحقق من أن المستخدم هو صاحب الصلاحية (اختياري)
    if str(chat_id) != MY_CHAT_ID:
        await update.message.reply_text("عذراً، لا تملك صلاحية الوصول.")
        return

    await update.message.reply_text("⏳ جاري سحب البيانات وتحليلها...")

    try:
        service = get_drive_service()
        # 1. تحميل الملف
        request = service.files().get_media(fileId=MY_FILE_ID)
        file_stream = io.BytesIO()
        downloader = MediaIoBaseDownload(file_stream, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        file_stream.seek(0)
        
        # 2. قراءة البيانات (Pandas)
        df = pd.read_excel(file_stream)
        
        # 3. إنشاء الصورة التحليلية (رسم بياني + جدول)
        # (هنا نستخدم نفس الكود السابق لإنشاء الصورة الاحترافية)
        plt.figure(figsize=(6, 4))
        plt.bar(df[df.columns[0]].apply(ar_text), df[df.columns[1]], color='#4CAF50')
        plt.title(ar_text("تحليل النتائج الحالية"))
        chart_buf = io.BytesIO()
        plt.savefig(chart_buf, format='png', dpi=100)
        chart_buf.seek(0)
        chart_img = Image.open(chart_buf)
        
        # 4. إرسال التقرير كصورة
        chart_buf.seek(0)
        await context.bot.send_photo(chat_id=chat_id, photo=chart_buf, caption="✅ تقريرك البصري جاهز!")
        
        # 5. إرسال نسخة من الملف الأصلي
        file_stream.seek(0)
        await context.bot.send_document(chat_id=chat_id, document=file_stream, filename="data_backup.xlsx")

    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")

if __name__ == '__main__':
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("report", send_report))
    print("🚀 البوت يعمل الآن.. أرسل /report في تليجرام")
    app.run_polling()
