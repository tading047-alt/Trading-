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
import logging

# إعداد السجلات (Logs) لمراقبة الأداء في Railway
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- الإعدادات الخاصة بك ---
SERVICE_ACCOUNT_FILE = 'credentials.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
MY_FILE_ID = "163bpUCuaPpOVTMs73y2cBSa6KCOxIXzIWk2NNonOTrs"
MY_CHAT_ID = "5067771509"

# دالة معالجة النصوص العربية للرسوم البيانية
def ar_text(text):
    try:
        if not isinstance(text, str): text = str(text)
        reshaped_text = arabic_reshaper.reshape(text)
        return get_display(reshaped_text)
    except:
        return text

# الاتصال بجوجل درايف
def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

# الوظيفة الأساسية للتقرير
async def send_report(update, context):
    chat_id = update.effective_chat.id
    
    # حماية: البوت لا يستجيب إلا لك (صاحب الـ Chat ID)
    if str(chat_id) != MY_CHAT_ID:
        await update.message.reply_text("🚫 عذراً، لا تملك صلاحية الوصول لهذا النظام.")
        return

    try:
        service = get_drive_service()
        
        # 1. إشعار الاتصال بنجاح (كما طلبت)
        # نقوم بمحاولة جلب معلومات الملف للتأكد من صحة الـ JSON والربط
        file_metadata = service.files().get(fileId=MY_FILE_ID).execute()
        
        await context.bot.send_message(
            chat_id=chat_id, 
            text="✅ تم الاتصال بـ قوقلدريف و ربط ملف google sheet بنجاح"
        )

        # 2. تحميل الملف في الذاكرة (Memory Stream)
        request = service.files().get_media(fileId=MY_FILE_ID)
        file_stream = io.BytesIO()
        downloader = MediaIoBaseDownload(file_stream, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        file_stream.seek(0)
        
        # 3. قراءة البيانات وإنشاء الرسم البياني باستخدام Pandas و Matplotlib
        df = pd.read_excel(file_stream)
        
        plt.figure(figsize=(10, 6))
        # استخدام أول عمودين (الأسماء والقيم)
        labels = df[df.columns[0]].apply(ar_text)
        values = df[df.columns[1]]
        
        plt.bar(labels, values, color='#1a73e8')
        plt.title(ar_text("تحليل البيانات اللحظي"))
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        
        chart_buf = io.BytesIO()
        plt.savefig(chart_buf, format='png', dpi=150, bbox_inches='tight')
        chart_buf.seek(0)
        
        # 4. إرسال الصورة والملف الأصلي
        await context.bot.send_photo(
            chat_id=chat_id, 
            photo=chart_buf, 
            caption=f"📊 تقرير البيانات المحدث من: {file_metadata.get('name')}"
        )
        
        file_stream.seek(0)
        await context.bot.send_document(
            chat_id=chat_id, 
            document=file_stream, 
            filename="trading_data_backup.xlsx",
            caption="📂 نسخة أصلية من ملف البيانات المستلم."
        )

    except Exception as e:
        await update.message.reply_text(f"🕵️ خطأ تقني: {str(e)}")

# رسالة الترحيب عند بدء التشغيل
async def start(update, context):
    await update.message.reply_text(
        "🤖 أهلاً بك في نظام الأتمتة الخاص بك.\n\n"
        "الأوامر المتاحة:\n"
        "📊 /report - جلب التقرير والبيانات من درايف."
    )

if __name__ == '__main__':
    # إنشاء تطبيق تليجرام
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # إضافة معالجات الأوامر
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("report", send_report))
    
    print("🚀 البوت يبدأ الآن على السحاب...")
    
    # تشغيل البوت مع تنظيف التحديثات المعلقة لحل مشكلة Conflict
    application.run_polling(drop_pending_updates=True)
