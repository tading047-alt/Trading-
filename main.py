import io
import pandas as pd
import matplotlib.pyplot as plt
from PIL import Image
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from telegram.ext import Application, CommandHandler
import arabic_reshaper
from bidi.algorithm import get_display
import asyncio

# --- الإعدادات الخاصة بك ---
SERVICE_ACCOUNT_FILE = 'credentials.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
MY_FILE_ID = "163bpUCuaPpOVTMs73y2cBSa6KCOxIXzIWk2NNonOTrs"
MY_CHAT_ID = "5067771509"

# دالة معالجة النصوص العربية للرسوم البيانية
def ar_text(text):
    if not isinstance(text, str): text = str(text)
    return get_display(arabic_reshaper.reshape(text))

# الاتصال بجوجل درايف
def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

# الوظيفة الأساسية للتقرير
async def send_report(update, context):
    chat_id = update.effective_chat.id
    
    # حماية: البوت لا يستجيب إلا لك
    if str(chat_id) != MY_CHAT_ID:
        await update.message.reply_text("🚫 عذراً، لا تملك صلاحية الوصول لهذا النظام.")
        return

    try:
        service = get_drive_service()
        
        # 1. إشعار الاتصال بنجاح (كما طلبت)
        file_metadata = service.files().get(fileId=MY_FILE_ID).execute()
        if file_metadata:
            await context.bot.send_message(
                chat_id=chat_id, 
                text="✅ تم الاتصال بـ قوقلدريف و ربط ملف google sheet بنجاح"
            )

        # 2. تحميل الملف في الذاكرة
        request = service.files().get_media(fileId=MY_FILE_ID)
        file_stream = io.BytesIO()
        downloader = MediaIoBaseDownload(file_stream, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        file_stream.seek(0)
        
        # 3. قراءة البيانات وإنشاء الرسم البياني
        df = pd.read_excel(file_stream)
        
        plt.figure(figsize=(8, 5))
        # نفترض أن العمود الأول هو الأسماء والثاني هو القيم
        plt.bar(df[df.columns[0]].apply(ar_text), df[df.columns[1]], color='#2ecc71')
        plt.title(ar_text("تحليل البيانات المحدثة"))
        
        chart_buf = io.BytesIO()
        plt.savefig(chart_buf, format='png', dpi=120)
        chart_buf.seek(0)
        
        # 4. إرسال الصورة والملف
        await context.bot.send_photo(
            chat_id=chat_id, 
            photo=chart_buf, 
            caption=f"📊 تقرير البيانات لملف: {file_metadata.get('name')}"
        )
        
        file_stream.seek(0)
        await context.bot.send_document(
            chat_id=chat_id, 
            document=file_stream, 
            filename="backup_data.xlsx",
            caption="📂 نسخة احتياطية من الملف الأصلي."
        )

    except Exception as e:
        await update.message.reply_text(f"❌ خطأ تقني: {str(e)}")

# رسالة الترحيب
async def start(update, context):
    await update.message.reply_text("🤖 أهلاً بك في نظام التداول والأتمتة الخاص بك.\nاستخدم /report لجلب أحدث التقارير.")

# تشغيل البوت مع معالجة الـ Conflict
if __name__ == '__main__':
    # بناء التطبيق
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # إضافة الأوامر
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("report", send_report))
    
    print("🚀 جاري تشغيل البوت وتنظيف الاتصالات القديمة...")
    
    # حل مشكلة Conflict على Railway: حذف أي Webhook قديم وتنظيف التحديثات
    application.run_polling(drop_pending_updates=True)
