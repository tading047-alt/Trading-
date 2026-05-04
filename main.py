#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import gspread
from google.oauth2.service_account import Credentials
from telegram import Bot
import os
import sys
from datetime import datetime

# ============================================
# 🔐 بيانات الاعتماد - أدخل بياناتك هنا
# ============================================

# بيانات Telegram (استبدلها ببياناتك)
TELEGRAM_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
TELEGRAM_CHAT_ID = "5067771509"

# بيانات Google Sheet
SHEET_ID = "163bpUCuaPpOVTMs73y2cBSa6KCOxIXzIWk2NNonOTrs"  # من رابط الملف
SHEET_NAME = "sheet1"  # اسم الورقة (غيرها إذا لزم الأمر)

# ملف JSON من Google Cloud (ضعه في نفس المجلد)
JSON_KEYFILE = "credentials.json"

# ============================================
# دوال الإشعارات
# ============================================

def send_telegram_message(message):
    """إرسال رسالة إلى Telegram"""
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        bot.send_message(
            chat_id=TELEGRAM_CHAT_ID, 
            text=message, 
            parse_mode='HTML'
        )
        print(f"✅ تم الإرسال إلى Telegram: {message[:50]}...")
        return True
    except Exception as e:
        print(f"❌ فشل الإرسال إلى Telegram: {e}")
        return False

def connect_to_google_sheet():
    """الاتصال بـ Google Sheets وإرسال الإشعارات"""
    try:
        # إشعار بدء الاتصال
        print("🔄 جاري الاتصال بـ Google Drive...")
        
        # إعداد الصلاحيات
        scope = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # التحقق من وجود ملف JSON
        if not os.path.exists(JSON_KEYFILE):
            raise Exception(f"ملف {JSON_KEYFILE} غير موجود!")
        
        # الاتصال بـ Google
        creds = Credentials.from_service_account_file(JSON_KEYFILE, scopes=scope)
        client = gspread.authorize(creds)
        
        # إرسال إشعار الاتصال بـ Drive
        send_telegram_message("✅ تم الاتصال بـ Google Drive بنجاح")
        
        # فتح ملف Google Sheet
        print("🔄 جاري فتح Google Sheet...")
        sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
        
        # إرسال إشعار فتح الملف
        send_telegram_message("✅ تم فتح Google Sheet بنجاح")
        
        # الحصول على معلومات إضافية
        sheet_title = sheet.title
        row_count = len(sheet.get_all_values())
        col_count = len(sheet.get_all_values()[0]) if row_count > 0 else 0
        
        # إرسال معلومات الملف
        info_message = f"""
📊 <b>معلومات الملف</b>
────────────────
📄 اسم الورقة: {sheet_title}
📏 عدد الصفوف: {row_count}
📐 عدد الأعمدة: {col_count}
🆔 معرف الملف: {SHEET_ID[:15]}...
📅 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        send_telegram_message(info_message)
        
        print("✅ تم إرسال جميع الإشعارات بنجاح")
        return sheet
        
    except Exception as e:
        error_msg = f"❌ خطأ: {str(e)}"
        print(error_msg)
        send_telegram_message(error_msg)
        return None

# ============================================
# التشغيل الرئيسي
# ============================================

def main():
    """الدالة الرئيسية"""
    print("=" * 50)
    print("🚀 بدء تشغيل برنامج إشعارات Telegram")
    print("=" * 50)
    
    # الاتصال وإرسال الإشعارات
    sheet = connect_to_google_sheet()
    
    if sheet:
        print("\n✨ تم الانتهاء بنجاح! تحقق من Telegram")
        # اختياري: طباعة أول 3 صفوف من البيانات
        try:
            data = sheet.get_all_values()[:3]
            print("\n📊 عينة من البيانات:")
            for i, row in enumerate(data, 1):
                print(f"   الصف {i}: {row[:3]}...")
        except:
            pass
    else:
        print("\n❌ فشل التشغيل. راجع الأخطاء أعلاه.")
    
    print("=" * 50)

# ============================================
# تشغيل البرنامج
# ============================================

if __name__ == "__main__":
    main()
