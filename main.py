# create_and_work.py
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime

# ============================================
# بياناتك - استبدلها ببياناتك
# ============================================

JSON_KEYFILE = "credentials.json"  # ملف JSON الخاص بك
YOUR_EMAIL = "elabed.elmouldi@gmail.com"  # بريدك الشخصي للمشاركة

# نطاقات الصلاحيات المطلوبة
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',  # لإنشاء وتعديل Sheets
    'https://www.googleapis.com/auth/drive'         # لإنشاء المجلدات
]

# ============================================
# الدوال الرئيسية
# ============================================

def create_folder_and_file():
    """
    إنشاء مجلد وملف Sheets جديد والعمل عليه
    """
    try:
        # 1. الاتصال بخدمات Google
        creds = Credentials.from_service_account_file(JSON_KEYFILE, scopes=SCOPES)
        gsheet_client = gspread.authorize(creds)  # للتعامل مع Sheets
        drive_service = build('drive', 'v3', credentials=creds)  # للتعامل مع Drive
        
        print("✅ تم الاتصال بـ Google Drive و Sheets")
        
        # ========================================
        # 2. إنشاء مجلد جديد
        # ========================================
        folder_name = f"تقرير_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        
        folder = drive_service.files().create(body=folder_metadata, fields='id, name, webViewLink').execute()
        folder_id = folder.get('id')
        folder_link = f"https://drive.google.com/drive/folders/{folder_id}"
        
        print(f"📁 تم إنشاء المجلد: {folder_name}")
        print(f"🔗 رابط المجلد: {folder_link}")
        
        # ========================================
        # 3. إنشاء ملف Sheets داخل المجلد
        # ========================================
        file_name = f"البيانات_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        file_metadata = {
            'name': file_name,
            'mimeType': 'application/vnd.google-apps.spreadsheet',
            'parents': [folder_id]  # هنا نحدد أن الملف داخل المجلد
        }
        
        file = drive_service.files().create(body=file_metadata, fields='id, name, webViewLink').execute()
        file_id = file.get('id')
        file_link = file.get('webViewLink')
        
        print(f"📄 تم إنشاء الملف: {file_name}")
        print(f"🔗 رابط الملف: {file_link}")
        
        # ========================================
        # 4. مشاركة المجلد مع بريدك الإلكتروني
        # ========================================
        permission = {
            'type': 'user',
            'role': 'writer',
            'emailAddress': YOUR_EMAIL
        }
        drive_service.permissions().create(fileId=folder_id, body=permission).execute()
        print(f"🔐 تمت مشاركة المجلد مع: {YOUR_EMAIL}")
        
        # ========================================
        # 5. فتح الملف وإضافة بيانات (العمل على الملف)
        # ========================================
        sheet = gsheet_client.open_by_key(file_id).sheet1
        
        # إضافة عنوان الأعمدة
        headers = ['الاسم', 'التاريخ', 'الكمية', 'السعر', 'الإجمالي']
        sheet.update([headers], 'A1')
        
        # إضافة بعض البيانات التجريبية
        data = [
            ['منتج 1', datetime.now().strftime('%Y-%m-%d'), '10', '50', '500'],
            ['منتج 2', datetime.now().strftime('%Y-%m-%d'), '5', '30', '150'],
            ['منتج 3', datetime.now().strftime('%Y-%m-%d'), '8', '20', '160']
        ]
        
        for i, row in enumerate(data, start=2):
            sheet.update([row], f'A{i}')
        
        print(f"✅ تم إضافة {len(data)} صف من البيانات")
        
        # ========================================
        # 6. قراءة البيانات التي أضفناها
        # ========================================
        all_data = sheet.get_all_values()
        print(f"\n📊 البيانات الموجودة في الملف:")
        print("-" * 50)
        for i, row in enumerate(all_data):
            print(f"الصف {i+1}: {' | '.join(row)}")
        
        # ========================================
        # 7. معلومات نهائية
        # ========================================
        print("\n" + "=" * 50)
        print("🎉 تم الإنشاء والعمل على الملف بنجاح!")
        print("=" * 50)
        print(f"📁 المجلد: {folder_name}")
        print(f"🔗 رابط المجلد: {folder_link}")
        print(f"📄 الملف: {file_name}")
        print(f"🔗 رابط الملف: {file_link}")
        print("=" * 50)
        
        return folder_id, file_id, sheet
        
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return None, None, None

def add_more_data(file_id, new_data):
    """
    إضافة بيانات إضافية إلى ملف موجود
    """
    try:
        creds = Credentials.from_service_account_file(JSON_KEYFILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(file_id).sheet1
        
        for row in new_data:
            sheet.append_row(row)
        
        print(f"✅ تم إضافة {len(new_data)} صف جديد")
        return True
        
    except Exception as e:
        print(f"❌ خطأ في الإضافة: {e}")
        return False

def read_file_data(file_id):
    """
    قراءة جميع البيانات من ملف موجود
    """
    try:
        creds = Credentials.from_service_account_file(JSON_KEYFILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(file_id).sheet1
        
        all_data = sheet.get_all_values()
        print(f"\n📊 البيانات من الملف:")
        for i, row in enumerate(all_data):
            print(f"الصف {i+1}: {row}")
        
        return all_data
        
    except Exception as e:
        print(f"❌ خطأ في القراءة: {e}")
        return None

# ============================================
# التشغيل الرئيسي
# ============================================

def main():
    print("=" * 50)
    print("🚀 بدء عملية إنشاء المجلد والملف")
    print("=" * 50)
    
    # إنشاء مجلد وملف والعمل عليه
    folder_id, file_id, sheet = create_folder_and_file()
    
    if file_id:
        print("\n📝 يمكنك الآن إضافة المزيد من البيانات:")
        
        # مثال: إضافة بيانات إضافية
        more_data = [
            ['منتج 4', datetime.now().strftime('%Y-%m-%d'), '12', '25', '300'],
            ['منتج 5', datetime.now().strftime('%Y-%m-%d'), '3', '100', '300']
        ]
        
        add_more_data(file_id, more_data)
        
        # قراءة البيانات النهائية
        read_file_data(file_id)

if __name__ == "__main__":
    main()
