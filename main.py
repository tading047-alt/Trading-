# test_final.py
import gspread

FILE_ID = "1RAWDvovHZZ7mEj9A0soo2XnPOudVadxu8KuZeQaR-dM"

print("🔄 جاري اختبار الاتصال...")

try:
    client = gspread.service_account(filename="credentials.json")
    print("✅ 1. الاتصال بـ Google Sheets ناجح")
    
    sheet = client.open_by_key(FILE_ID).sheet1
    print(f"✅ 2. تم فتح الملف: {sheet.title}")
    
    data = sheet.get_all_values()
    print(f"✅ 3. تم قراءة {len(data)} صف")
    
    print("\n🎉 كل شيء يعمل! الآن شغل main.py")
    
except Exception as e:
    print(f"❌ خطأ: {e}")
