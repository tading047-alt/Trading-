# -*- coding: utf-8 -*-
"""تحليل البيانات وإرسال النتائج كرسائل نصية إلى Email - WhatsApp - Telegram"""

import pandas as pd
import sqlite3
import os
from google.colab import drive
import yagmail
import pywhatkit as kit
import requests
from datetime import datetime

print("="*60)
print("📊 مشروع تحليل البيانات وإرسال النتائج")
print("="*60)

# ============================================
# 1. تحميل Google Drive
# ============================================
print("\n📁 جاري تحميل Google Drive...")
drive.mount('/content/drive')
print("✅ تم تحميل Google Drive بنجاح!")

# ============================================
# 2. تحديد مسار المجلد
# ============================================
folder_path = '/content/drive/MyDrive/sales_data/'
!mkdir -p "{folder_path}"

# ============================================
# 3. إنشاء أو تحميل البيانات
# ============================================
def load_or_create_data(path):
    """تحميل البيانات من Drive أو إنشاؤها"""
    
    db_file = os.path.join(path, 'sales.db')
    csv_file = os.path.join(path, 'sales_q2.csv')
    excel_file = os.path.join(path, 'sales_q3.xlsx')
    
    # إنشاء الملفات إذا لم تكن موجودة
    if not os.path.exists(db_file):
        print("📝 إنشاء ملفات تجريبية...")
        conn = sqlite3.connect(db_file)
        q1_data = pd.DataFrame({
            'id': [1, 2, 3, 4, 5],
            'product_name': ['لابتوب', 'ماوس', 'لوحة مفاتيح', 'شاشة', 'طابعة'],
            'quantity': [5, 20, 15, 8, 3],
            'price': [2500, 50, 150, 800, 600],
            'sale_date': ['2024-01-15', '2024-01-20', '2024-02-10', '2024-02-25', '2024-03-05'],
            'region': ['الرياض', 'جدة', 'الدمام', 'الرياض', 'جدة']
        })
        q1_data.to_sql('sales', conn, if_exists='replace', index=False)
        conn.close()
        
        q2_data = pd.DataFrame({
            'id': [6, 7, 8, 9, 10],
            'product_name': ['لابتوب', 'سماعة', 'ماوس', 'كاميرا', 'شاحن'],
            'quantity': [7, 25, 30, 4, 40],
            'price': [2400, 120, 45, 1500, 80],
            'sale_date': ['2024-04-12', '2024-04-18', '2024-05-05', '2024-05-20', '2024-06-15'],
            'region': ['الرياض', 'الدمام', 'جدة', 'الرياض', 'الخبر']
        })
        q2_data.to_csv(csv_file, index=False)
        
        q3_data = pd.DataFrame({
            'id': [11, 12, 13, 14, 15],
            'product_name': ['لابتوب', 'سماعة', 'طابعة', 'ماوس', 'لوحة مفاتيح'],
            'quantity': [6, 35, 5, 45, 20],
            'price': [2450, 110, 580, 48, 140],
            'sale_date': ['2024-07-10', '2024-07-25', '2024-08-15', '2024-08-30', '2024-09-05'],
            'region': ['جدة', 'الرياض', 'الدمام', 'الخبر', 'الرياض']
        })
        q3_data.to_excel(excel_file, index=False)
        print("✅ تم إنشاء الملفات التجريبية")
    
    return db_file, csv_file, excel_file

db_path, csv_path, excel_path = load_or_create_data(folder_path)

# ============================================
# 4. تحميل البيانات وتحليلها
# ============================================
print("\n🔄 جاري تحميل وتحليل البيانات...")

# تحميل البيانات
conn = sqlite3.connect(db_path)
df_q1 = pd.read_sql_query("SELECT *, 'Q1' as quarter FROM sales;", conn)
conn.close()

df_q2 = pd.read_csv(csv_path)
df_q2['quarter'] = 'Q2'

df_q3 = pd.read_excel(excel_path, engine='openpyxl')
df_q3['quarter'] = 'Q3'

# دمج البيانات
df_all = pd.concat([df_q1, df_q2, df_q3], ignore_index=True)
df_all['total_revenue'] = df_all['quantity'] * df_all['price']
df_all['sale_date'] = pd.to_datetime(df_all['sale_date'])

# ============================================
# 5. إنشاء نص الرسالة (ملخص التحليل)
# ============================================
def create_message_text():
    """إنشاء نص الرسالة مع ملخص التحليل"""
    
    # حساب الإحصائيات
    total_revenue = df_all['total_revenue'].sum()
    total_quantity = df_all['quantity'].sum()
    avg_price = df_all['price'].mean()
    total_transactions = len(df_all)
    
    # أفضل المنتجات
    top_products = df_all.groupby('product_name')['total_revenue'].sum().sort_values(ascending=False).head(3)
    
    # الإيرادات حسب المنطقة
    revenue_by_region = df_all.groupby('region')['total_revenue'].sum().sort_values(ascending=False)
    
    # التحليل الربعي
    quarterly = df_all.groupby('quarter')['total_revenue'].sum()
    
    # بناء الرسالة
    message = f"""
╔══════════════════════════════════════════════════════╗
║           📊 تقرير تحليل المبيعات               ║
║              {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}              ║
╚══════════════════════════════════════════════════════╝

📈 ملخص عام:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• إجمالي الإيرادات: {total_revenue:,.2f} ريال
• إجمالي الكميات المباعة: {total_quantity:,} وحدة
• متوسط سعر المنتج: {avg_price:.2f} ريال
• عدد المعاملات: {total_transactions} عملية

🏆 أفضل 3 منتجات من حيث الإيرادات:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    for i, (product, revenue) in enumerate(top_products.items(), 1):
        message += f"{i}. {product}: {revenue:,.2f} ريال\n"
    
    message += "\n💰 الإيرادات حسب المنطقة:\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for region, revenue in revenue_by_region.items():
        message += f"• {region}: {revenue:,.2f} ريال\n"
    
    message += "\n📅 الإيرادات حسب الربع:\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for quarter, revenue in quarterly.items():
        message += f"• الربع {quarter}: {revenue:,.2f} ريال\n"
    
    message += """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✨ تم إنشاء هذا التقرير تلقائياً بواسطة نظام التحليل الذكي
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    return message

# إنشاء نص الرسالة
message_text = create_message_text()

# عرض الرسالة قبل الإرسال
print("\n" + "="*60)
print("📝 نص الرسالة التي سيتم إرسالها:")
print("="*60)
print(message_text)

# ============================================
# 6. دوال الإرسال
# ============================================

# 6.1 إرسال إلى البريد الإلكتروني
def send_email_message(receiver_email, subject, message):
    """إرسال رسالة نصية إلى البريد الإلكتروني"""
    try:
        # ⚠️ أدخل بيانات حسابك هنا
        sender_email = "your_email@gmail.com"  # غيّر إلى بريدك
        app_password = "your_app_password"      # غيّر إلى كلمة مرور التطبيق
        
        yag = yagmail.SMTP(user=sender_email, password=app_password)
        yag.send(to=receiver_email, subject=subject, contents=message)
        print("✅ تم إرسال الرسالة إلى البريد الإلكتروني")
        return True
    except Exception as e:
        print(f"❌ فشل إرسال البريد: {e}")
        return False

# 6.2 إرسال إلى واتساب (رسالة نصية)
def send_whatsapp_message(phone_number, message):
    """إرسال رسالة نصية إلى واتساب"""
    try:
        # phone_number: يجب أن يكون مع رمز الدولة، مثال: "+9665XXXXXXXX"
        # wait_time: وقت الانتظار بالثواني قبل الإرسال
        kit.sendwhatmsg_instantly(phone_no=phone_number, message=message, wait_time=20, tab_close=True)
        print("✅ تم إرسال الرسالة إلى واتساب")
        print("   📌 ملاحظة: تأكد من تسجيل الدخول إلى WhatsApp Web")
        return True
    except Exception as e:
        print(f"❌ فشل إرسال واتساب: {e}")
        return False

# 6.3 إرسال إلى تليجرام
def send_telegram_message(bot_token, chat_id, message):
    """إرسال رسالة نصية إلى تليجرام"""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }
        response = requests.post(url, json=payload)
        
        if response.status_code == 200:
            print("✅ تم إرسال الرسالة إلى تليجرام")
            return True
        else:
            print(f"❌ فشل إرسال تليجرام: {response.text}")
            return False
    except Exception as e:
        print(f"❌ خطأ في تليجرام: {e}")
        return False

# ============================================
# 7. إدخال بيانات الإرسال
# ============================================

print("\n" + "="*60)
print("📤 إعدادات الإرسال:")
print("="*60)

# تخزين نتائج الإرسال
send_results = {}

# 7.1 البريد الإلكتروني
send_email_choice = input("\nهل تريد إرسال الرسالة إلى البريد الإلكتروني؟ (نعم/لا): ").strip().lower()
if send_email_choice in ['نعم', 'yes', 'y']:
    receiver_email = input("أدخل البريد الإلكتروني المستلم: ").strip()
    subject = "📊 تقرير تحليل المبيعات"
    send_results['Email'] = send_email_message(receiver_email, subject, message_text)

# 7.2 واتساب
send_whatsapp_choice = input("\nهل تريد إرسال الرسالة إلى واتساب؟ (نعم/لا): ").strip().lower()
if send_whatsapp_choice in ['نعم', 'yes', 'y']:
    phone = input("أدخل رقم الهاتف مع رمز الدولة (مثال: +966512345678): ").strip()
    send_results['WhatsApp'] = send_whatsapp_message(phone, message_text)

# 7.3 تليجرام
send_telegram_choice = input("\nهل تريد إرسال الرسالة إلى تليجرام؟ (نعم/لا): ").strip().lower()
if send_telegram_choice in ['نعم', 'yes', 'y']:
    print("\n📌 للحصول على توكن البوت ومعرف المحادثة:")
    print("   1. ابحث عن @BotFather في تليجرام وأنشئ بوت جديد")
    print("   2. ابحث عن @userinfobot لتحصل على معرف المحادثة الخاص بك")
    
    bot_token = input("أدخل توكن البوت (Bot Token): ").strip()
    chat_id = input("أدخل معرف المحادثة (Chat ID): ").strip()
    send_results['Telegram'] = send_telegram_message(bot_token, chat_id, message_text)

# ============================================
# 8. تقرير النتائج النهائي
# ============================================
print("\n" + "="*60)
print("📋 تقرير نتائج الإرسال:")
print("="*60)

for platform, status in send_results.items():
    icon = "✅" if status else "❌"
    print(f"{icon} {platform}: {'تم الإرسال بنجاح' if status else 'فشل الإرسال'}")

# حفظ الرسالة في ملف (نسخة احتياطية)
with open('analysis_report.txt', 'w', encoding='utf-8') as f:
    f.write(message_text)
print("\n💾 تم حفظ نسخة من التقرير في: analysis_report.txt")

print("\n" + "="*60)
print("🎉 اكتمل التحليل والإرسال!")
print("="*60)
