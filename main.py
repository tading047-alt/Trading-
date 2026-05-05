# create_folder_and_file.py
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import telegram
from datetime import datetime

# ============================================
# بياناتك
# ============================================

TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
TELEGRAM_CHAT_ID = "5067771509"
YOUR_EMAIL = "elabed.elmouldi@gmail.com"  # بريدك الشخصي لمشاركة المجلد والملف

# نطاقات الصلاحيات (نحتاج Drive API أيضاً)
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def send_telegram(message):
    """إرسال رسالة إلى Telegram"""
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
        print("✅ تم الإرسال إلى Telegram")
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")

def create_folder_and_file():
    """
    إنشاء مجلد جديد في Google Drive وإنشاء ملف Google Sheets بداخله
    """
    try:
        # 1. الاتصال بـ Google Drive و Sheets
        creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
        
        # عميل gspread للتعامل مع Sheets
        client = gspread.authorize(creds)
        
        # خدمة Drive API للتعامل مع المجلدات
        drive_service = build('drive', 'v3', credentials=creds)
        
        send_telegram("✅ تم الاتصال بـ Google Drive بنجاح")
        
        # 2. إنشاء مجلد جديد
        folder_name = f"تقريرات_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        
        folder = drive_service.files().create(body=folder_metadata, fields='id').execute()
        folder_id = folder.get('id')
        
        send_telegram(f"✅ تم إنشاء مجلد جديد\n📁 الاسم: {folder_name}\n🆔 المعرف: {folder_id}")
        
        # 3. إنشاء ملف Google Sheets داخل المجلد
        file_name = f"البيانات_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # إنشاء الملف في المجلد المحدد
        file_metadata = {
            'name': file_name,
            'mimeType': 'application/vnd.google-apps.spreadsheet',
            'parents': [folder_id]  # هنا نحدد المجلد الذي سيُوضع فيه الملف
        }
        
        file = drive_service.files().create(body=file_metadata, fields='id, webViewLink').execute()
        file_id = file.get('id')
        file_link = file.get('webViewLink')
        
        send_telegram(f"✅ تم إنشاء ملف Google Sheets داخل المجلد\n📄 الاسم: {file_name}\n🔗 الرابط: {file_link}")
        
        # 4. مشاركة المجلد مع بريدك الإلكتروني (لرؤيته)
        permission = {
            'type': 'user',
            'role': 'writer',
            'emailAddress': YOUR_EMAIL
        }
        drive_service.permissions().create(fileId=folder_id, body=permission).execute()
        
        # 5. فتح الملف باستخدام gspread لإضافة بيانات (اختياري)
        sheet = client.open_by_key(file_id).sheet1
        
        # إضافة عنوان الأعمدة
        sheet.update([['الاسم', 'التاريخ', 'البيانات', 'الملاحظات']], 'A1')
        
        # إضافة صف مثال
        sheet.append_row(['مثال', str(datetime.now()), 'تم الإنشاء تلقائياً', 'ناجح'])
        
        # 6. إرسال المعلومات النهائية إلى Telegram
        final_info = f"""
📊 <b>تم الإنشاء بنجاح</b>
─────────────────────
📁 اسم المجلد: {folder_name}
🆔 معرف المجلد: {folder_id}

📄 اسم الملف: {file_name}
🆔 معرف الملف: {file_id}
🔗 رابط الملف: {file_link}
─────────────────────
📅 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        send_telegram(final_info)
        
        print(f"\n✅ تم إنشاء المجلد والملف بنجاح!")
        print(f"📁 المجلد: {folder_name}")
        print(f"📄 الملف: {file_name}")
        print(f"🔗 الرابط: {file_link}")
        
        return folder_id, file_id
        
    except Exception as e:
        error_msg = f"❌ خطأ: {str(e)}"
        print(error_msg)
        send_telegram(error_msg)
        return None, None

def main():
    print("=" * 50)
    print("🚀 بدء إنشاء مجلد وملف جديد في Google Drive")
    print("=" * 50)
    
    create_folder_and_file()

if __name__ == "__main__":
    main()
