import io
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ['https://www.googleapis.com/auth/drive']

creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
service = build('drive', 'v3', credentials=creds)

FILE_ID = 'PUT_FILE_ID_HERE'

request = service.files().get_media(fileId=FILE_ID)
file = io.BytesIO()

downloader = MediaIoBaseDownload(file, request)

done = False
while done is False:
    status, done = downloader.next_chunk()

file.seek(0)

df = pd.read_excel(file)

print(df.head())
