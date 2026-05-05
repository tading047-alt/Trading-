# alt_method.py
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import json

SHEET_ID = "1RAWDvovHZZ7mEj9A0soo2XnPOudVadxu8KuZeQaR-dM"
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

# تحميل credentials
with open("credentials.json", "r") as f:
    creds_data = json.load(f)

# إنشاء credentials
creds = Credentials.from_service_account_info(creds_data, scopes=SCOPES)

# بناء الخدمة
service = build('sheets', 'v4', credentials=creds)

# محاولة القراءة
try:
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range='Sheet1!A1:A10'
    ).execute()
    print("✅ نجح! البيانات:", result.get('values', []))
except Exception as e:
    print(f"❌ فشل: {e}")
