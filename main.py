# test_new.py
import gspread
import json

print("=" * 50)
print("اختبار الملف الجديد")
print("=" * 50)

# 1. قراءة الملف
try:
    with open("credentials.json", "r") as f:
        data = json.load(f)
        print("✅ 1. ملف JSON موجود")
        print(f"   البريد: {data['client_email']}")
        print(f"   المشروع: {data['project_id']}")
except Exception as e:
    print(f"❌ 1. فشل قراءة الملف: {e}")
    exit()

# 2. اختبار الاتصال
try:
    client = gspread.service_account(filename="credentials.json")
    print("✅ 2. الاتصال ناجح")
except Exception as e:
    print(f"❌ 2. فشل الاتصال: {e}")
    exit()

# 3. فتح الملف
FILE_ID = "1RAWDvovHZZ7mEj9A0soo2XnPOudVadxu8KuZeQaR-dM"
try:
    sheet = client.open_by_key(FILE_ID).sheet1
    print(f"✅ 3. تم فتح الملف: {sheet.title}")
except Exception as e:
    print(f"❌ 3. فشل فتح الملف: {e}")
    print("   ⚠️ تأكد من مشاركة الملف مع البريد الإلكتروني أعلاه")
    exit()

print("\n🎉 كل شيء يعمل! الآن شغل البرنامج الرئيسي.")
