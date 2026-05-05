# test_with_id.py
import gspread
from google.oauth2.service_account import Credentials
import json

# معرف الملف (من رابطك)
FILE_ID = "1RAWDvovHZZ7mEj9A0soo2XnPOudVadxu8KuZeQaR-dM"

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

print("=" * 50)
print("اختبار فتح الملف باستخدام ID")
print("=" * 50)

try:
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    client = gspread.authorize(creds)
    print("✅ الاتصال ناجح")
    
    # فتح الملف باستخدام ID مباشرة
    spreadsheet = client.open_by_key(FILE_ID)
    print(f"✅ تم فتح الملف: {spreadsheet.title}")
    
    sheet = spreadsheet.sheet1
    data = sheet.get_all_values()
    print(f"✅ تم قراءة {len(data)} صف")
    print(f"🎉 النجاح!")
    
except Exception as e:
    print(f"❌ فشل: {e}")
