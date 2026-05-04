# test.py - اختبر اتصالك أولاً
import gspread
import json

print("=" * 40)
print("اختبار الاتصال بـ Google Sheets")
print("=" * 40)

# 1. التحقق من ملف JSON
try:
    with open("credentials.json", "r") as f:
        data = json.load(f)
        print("✅ 1/4 ملف JSON موجود وصالح")
        print(f"   📧 البريد: {data['client_email']}")
except Exception as e:
    print(f"❌ 1/4 ملف JSON: {e}")
    exit()

# 2. الاتصال بخدمة Google
try:
    client = gspread.service_account(filename="credentials.json")
    print("✅ 2/4 الاتصال بـ Google Sheets ناجح")
except Exception as e:
    print(f"❌ 2/4 فشل الاتصال: {e}")
    exit()

# 3. فتح الملف بالمعرف الجديد
FILE_ID = "1RAWDvovHZZ7mEj9A0soo2XnPOudVadxu8KuZeQaR-dM"
try:
    spreadsheet = client.open_by_key(FILE_ID)
    print(f"✅ 3/4 تم فتح الملف: {spreadsheet.title}")
except Exception as e:
    print(f"❌ 3/4 فشل فتح الملف: {e}")
    print("   ⚠️ تأكد من مشاركة الملف مع البريد الإلكتروني أعلاه")
    exit()

# 4. قراءة البيانات
try:
    sheet = spreadsheet.sheet1
    rows = sheet.get_all_values()
    print(f"✅ 4/4 تم قراءة {len(rows)} صف و {len(rows[0]) if rows else 0} عمود")
except Exception as e:
    print(f"❌ 4/4 فشل قراءة البيانات: {e}")
    exit()

print("\n🎉 كل شيء يعمل! يمكنك تشغيل البرنامج الرئيسي.")
