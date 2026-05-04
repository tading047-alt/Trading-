import io
import pandas as pd
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from telegram.ext import Application, CommandHandler

# Configuration des logs pour surveiller le bot sur Railway
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)

# --- Vos configurations validées ---
SERVICE_ACCOUNT_FILE = 'credentials.json'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
# ID extrait de votre nouveau lien
MY_FILE_ID = "1RAWDvovHZZ7mEj9A0soo2XnPOudVadxu8KuZeQaR-dM"
MY_CHAT_ID = "5067771509"
SHEET_NAME = "sheet1"

def get_drive_service():
    """Authentification via le fichier credentials.json"""
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

async def check_connection(update, context):
    """Fonction qui vérifie la connexion et envoie la notification"""
    chat_id = update.effective_chat.id
    
    # Sécurité : Seul vous pouvez utiliser cette commande
    if str(chat_id) != MY_CHAT_ID:
        await update.message.reply_text("🚫 Accès non autorisé.")
        return

    try:
        # 1. Connexion au service Google Drive
        service = get_drive_service()
        
        # 2. Tentative d'accès aux métadonnées du fichier
        file_metadata = service.files().get(fileId=MY_FILE_ID).execute()
        
        # 3. Notification de succès immédiate (Demande utilisateur)
        await context.bot.send_message(
            chat_id=chat_id, 
            text="✅ تم الاتصال بـ قوقلدريف و ربط ملف google sheet بنجاح"
        )

        # 4. Lecture des données pour confirmer l'accès au contenu
        request = service.files().get_media(fileId=MY_FILE_ID)
        file_stream = io.BytesIO()
        downloader = MediaIoBaseDownload(file_stream, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        
        file_stream.seek(0)
        # Charge la feuille spécifiée
        df = pd.read_excel(file_stream, sheet_name=SHEET_NAME)
        
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"📊 Données chargées avec succès.\nNombre de lignes : {len(df)}"
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Échec de la connexion : {str(e)}")

async def start(update, context):
    """Message de bienvenue"""
    await update.message.reply_text(
        "🤖 Bot de liaison Google Sheets prêt.\n"
        "Utilisez /check pour tester la connexion."
    )

if __name__ == '__main__':
    # Initialisation du bot Telegram
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Ajout des commandes
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_connection))
    
    print("🚀 Le bot est en ligne...")
    
    # Utilisation de drop_pending_updates pour éviter les conflits sur Railway
    application.run_polling(drop_pending_updates=True)
