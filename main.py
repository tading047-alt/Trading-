# test_new_key.py
import gspread
import json

# 1. تحقق من الملف
with open("credentials.json", "r") as f:
    data = json.load(f)
    print(f"✅ الملف موجود")
    print(f"📧 البريد: {data['client_email']}")
    print(f"🆔 المشروع: {data['project_id']}")

# 2. اختبر الاتصال
try:
    client = gspread.service_account(filename="credentials.json")
    print("✅ الاتصال بـ Google Sheets ناجح!")
    
    # اختبر فتح ملف (اختياري)
    # sheet = client.open_by_key("163bpUCuaPpOVTMs73y2cBSa6KCOxIXzIWk2NNonOTrs")
    # print(f"✅ تم فتح الملف: {sheet.title}")
    
except Exception as e:
    print(f"❌ فشل: {e}")
