import io
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# الصلاحيات
SCOPES = ["https://www.googleapis.com/auth/drive"]

creds = Credentials.from_service_account_file(
    "credentials.json",
    scopes=SCOPES
)

service = build("drive", "v3", credentials=creds)

# 📊 بيانات تجريبية
data = {
    "coin": ["BTC", "ETH", "SOL"],
    "price": [65000, 3200, 150]
}

df = pd.DataFrame(data)

# 📁 تحويل Excel في الذاكرة
file_buffer = io.BytesIO()
df.to_excel(file_buffer, index=False)
file_buffer.seek(0)

# 📌 رفع الملف إلى Google Drive
file_metadata = {
    "name": "trading_data.xlsx",
    "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
}

media = MediaIoBaseUpload(
    file_buffer,
    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

file = service.files().create(
    body=file_metadata,
    media_body=media,
    fields="id"
).execute()

print("FILE CREATED ✅ ID:", file.get("id"))
