import io
import pandas as pd
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from telegram.ext import Application, CommandHandler

# Configuration des logs pour Railway
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- Vos configurations mises à jour ---
SERVICE_ACCOUNT_FILE = 'credentials.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
MY_FILE_ID = "1RAWDvovHZZ7mEj9A0soo2XnPOudVadxu8KuZeQaR-dM" # Nouvel ID mis à jour
MY_CHAT_ID = "5067771509"
SHEET_NAME = "sheet1"

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

async def check_connection(update, context):
    chat_id = update.effective_chat.id
    
    if str(chat_id) != MY_CHAT_ID:
        await update.message.reply_text("🚫 Accès refusé.")
        return

    try:
        service = get_drive_service()
        
        # 1. Vérification de la connexion au fichier
        file_metadata = service.files().get(fileId=MY_FILE_ID).execute()
        
        # 2. Notification de succès (comme demandé)
        await context.bot.send_message(
            chat_id=chat_id, 
            text="✅ تم الاتصال بـ قوقلدريف و ربط ملف google sheet بنجاح"
        )

        # 3. Test de lecture des données
        request = service.files().get_media(fileId=MY_FILE_ID)
        file_stream = io.BytesIO()
        downloader = MediaIoBaseDownload(file_stream, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        
        file_stream.seek(0)
        df = pd.read_excel(file_stream, sheet_name=SHEET_NAME)
        
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"📊 Connexion à la feuille ({SHEET_NAME}) réussie.\nLignes trouvées : {len(df)}"
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Échec de la connexion : {str(e)}\nAssurez-vous de partager le fichier avec l'e-mail du compte de service.")

async def start(update, context):
    await update.message.reply_text("🤖 Bot prêt. Utilisez /check pour tester la liaison avec Google Sheets.")

if __name__ == '__main__':
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_connection))
    
    print("🚀 Le bot est en cours d'exécution...")
    application.run_polling(drop_pending_updates=True)
