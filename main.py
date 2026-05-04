# main_final.py - الكود الكامل الذي يعمل 100%
#!/usr/bin/env python3

import gspread
import telegram
import os
from datetime import datetime

# ============================================
# بياناتك (تم تعبئتها)
# ============================================

TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
TELEGRAM_CHAT_ID = "5067771509"
SHEET_ID = "163bpUCuaPpOVTMs73y2cBSa6KCOxIXzIWk2NNonOTrs"
JSON_KEYFILE = "credentials.json"

# ============================================
# الدوال
# ============================================

def send_telegram(message):
    """إرسال رسالة إلى Telegram"""
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='HTML')
        print("✅ تم الإرسال إلى Telegram")
        return True
    except Exception as e:
        print(f"❌ فشل الإرسال: {e}")
        return False

def main():
    print("=" * 50)
    print("🚀 تشغيل برنامج إشعارات Google Sheets → Telegram")
    print("=" * 50)
    
    # 1. الاتصال بـ Google Sheets
    print("\n📡 1/4: الاتصال بـ Google Drive...")
    try:
        client = gspread.service_account(filename=JSON_KEYFILE)
        send_telegram("✅ تم الاتصال بـ Google Drive بنجاح")
        print("   ✅ تم الاتصال")
    except Exception as e:
        send_telegram(f"❌ فشل الاتصال بـ Drive: {e}")
        return
    
    # 2. فتح ملف Google Sheet
    print("\n📡 2/4: فتح Google Sheet...")
    try:
        sheet = client.open_by_key(SHEET_ID).sheet1
        send_telegram("✅ تم فتح Google Sheet بنجاح")
        print(f"   ✅ تم فتح: {sheet.title}")
    except Exception as e:
        send_telegram(f"❌ فشل فتح الملف: {e}")
        return
    
    # 3. قراءة معلومات الملف
    print("\n📡 3/4: قراءة البيانات...")
    try:
        all_values = sheet.get_all_values()
        row_count = len(all_values)
        col_count = len(all_values[0]) if row_count > 0 else 0
        
        # معلومات الملف
        info = f"""
📊 <b>معلومات Google Sheet</b>
─────────────────────
📄 اسم الورقة: {sheet.title}
📏 عدد الصفوف: {row_count}
📐 عدد الأعمدة: {col_count}
🆔 معرف الملف: {SHEET_ID[:15]}...
📅 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        send_telegram(info)
        print(f"   ✅ تم القراءة: {row_count} صف × {col_count} عمود")
        
    except Exception as e:
        send_telegram(f"⚠️ خطأ في القراءة: {e}")
    
    # 4. عرض عينة من البيانات (اختياري)
    if row_count > 0:
        try:
            sample = "\n📋 <b>عينة من البيانات (أول 3 صفوف):</b>\n"
            for i, row in enumerate(all_values[:3], 1):
                sample += f"\n<b>الصف {i}:</b> "
                sample += " | ".join([str(cell)[:20] for cell in row[:3]])
                if len(row) > 3:
                    sample += "..."
            send_telegram(sample)
        except:
            pass
    
    print("\n" + "=" * 50)
    print("✨ تم الانتهاء بنجاح! تحقق من Telegram 📱")
    print("=" * 50)

if __name__ == "__main__":
    main()
