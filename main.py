# main.py
import warnings
warnings.filterwarnings('ignore', category=FutureWarning)

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
YOUR_EMAIL = "elabed.elmouldi@gmail.com"

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def send_telegram(message):
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
        print("✅ تم الإرسال")
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")

def create_folder_and_file():
    try:
        creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
        client = gspread.authorize(creds)
        drive_service = build('drive', 'v3', credentials=creds)
        
        send_telegram("✅ تم الاتصال بـ Google Drive بنجاح")
        
        # إنشاء مجلد
        folder_name = f"تقريرات_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = drive_service.files().create(body=folder_metadata, fields='id').execute()
        folder_id = folder.get('id')
        
        send_telegram(f"✅ تم إنشاء مجلد: {folder_name}")
        
        # إنشاء ملف داخل المجلد
        file_name = f"البيانات_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        file_metadata = {
            'name': file_name,
            'mimeType': 'application/vnd.google-apps.spreadsheet',
            'parents': [folder_id]
        }
        file = drive_service.files().create(body=file_metadata, fields='id, webViewLink').execute()
        file_link = file.get('webViewLink')
        
        send_telegram(f"✅ تم إنشاء ملف داخل المجلد\n🔗 {file_link}")
        
        # مشاركة المجلد مع بريدك
        permission = {
            'type': 'user',
            'role': 'writer',
            'emailAddress': YOUR_EMAIL
        }
        drive_service.permissions().create(fileId=folder_id, body=permission).execute()
        
        send_telegram(f"📊 تمت المشاركة مع: {YOUR_EMAIL}")
        
        print(f"✅ تم الإنشاء بنجاح!\n📁 {folder_name}\n📄 {file_name}")
        
    except Exception as e:
        send_telegram(f"❌ خطأ: {str(e)}")

def main():
    print("🚀 بدء الإنشاء...")
    create_folder_and_file()

if __name__ == "__main__":
    main()
