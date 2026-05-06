import pandas as pd
import gspread
import os
import json
from google.oauth2.service_account import Credentials

# ✅ قراءة credentials من ENV (Railway)
creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

client = gspread.authorize(creds)

# ✅ Google Sheet ID
sheet = client.open_by_key("1RAWDvovHZZ7mEj9A0soo2XnPOudVadxu8KuZeQaR-dM").sheet1

# ✅ قراءة البيانات
data = sheet.get_all_records()

df = pd.DataFrame(data)

print("DATA LOADED ✅")
print(df.head())
