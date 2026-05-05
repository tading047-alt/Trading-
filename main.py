# test_auth.py
import gspread
from google.oauth2.service_account import Credentials
import json

# اقرأ البريد من ملف JSON
with open("credentials.json", "r") as f:
    data = json.load(f)
    email_in_json = data['client_email']
    print(f"📧 البريد في ملف JSON: {email_in_json}")

print("\n⚠️ تأكد من مشاركة ملف 'Produits' مع هذا البريد!")
print(f"   البريد: {email_in_json}")
print("   الصلاحية: Editor\n")

# اختبار الاتصال
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

try:
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    client = gspread.authorize(creds)
    print("✅ الاتصال ناجح")
    
    # محاولة فتح الملف
    sheet = client.open('Produits').sheet1
    print(f"✅ تم فتح الملف: {sheet.spreadsheet.title}")
    print(f"✅ عدد الصفوف: {len(sheet.get_all_values())}")
    
except Exception as e:
    print(f"❌ فشل: {e}")
