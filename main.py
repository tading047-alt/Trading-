import pandas as pd
import os
import requests

# إعدادات تلغرام (تأكد من وضعها في Variables بداخل Railway)
BOT_TOKEN = os.getenv('TELEGRAM_TOKEN', '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo')
CHAT_ID = os.getenv('CHAT_ID', '5067771509')

def send_telegram_file(file_path, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, 'rb') as file:
            payload = {'chat_id': CHAT_ID, 'caption': caption}
            files = {'document': file}
            response = requests.post(url, data=payload, files=files)
            if response.status_code == 200:
                print(f"🚀 تم إرسال {file_path} بنجاح!")
            else:
                print(f"❌ فشل الإرسال: {response.text}")
    except Exception as e:
        print(f"❌ خطأ أثناء الإرسال: {e}")

def analyze_all_clients():
    input_file = 'data/Large_Sales_Purchases_Data.xlsx'
    # اسم الملف الجديد الذي سيحتوي على الإحصائيات
    output_analysis_file = 'output/clients_statistics.xlsx'

    if not os.path.exists('output'):
        os.makedirs('output')

    if os.path.exists(input_file):
        print("📖 جاري تحليل بيانات جميع العملاء...")
        df = pd.read_excel(input_file)

        # تحليل البيانات:
        # 1. حساب إجمالي المبالغ لكل عميل
        # 2. حساب عدد العمليات (count) لكل عميل
        client_stats = df.groupby('الجهة (عميل/مورد)').agg({
            'الإجمالي': 'sum',
            'رقم العملية': 'count'
        }).reset_index()

        # إعادة تسمية الأعمدة لتكون واضحة في ملف الأكسل الجديد
        client_stats.columns = ['اسم العميل/المورد', 'إجمالي المبالغ', 'عدد المعاملات']

        # ترتيب العملاء من الأكثر تعاملاً مالياً
        client_stats = client_stats.sort_values(by='إجمالي المبالغ', ascending=False)

        # حفظ الجدول الجديد في ملف أكسل
        client_stats.to_excel(output_analysis_file, index=False)
        print(f"✅ تم إنشاء جدول الإحصائيات: {output_analysis_file}")

        # إرسال الملف الجديد إلى تلغرام
        caption = "📊 جدول إحصائيات جميع العملاء (الإجمالي وعدد المعاملات)"
        send_telegram_file(output_analysis_file, caption)
        
    else:
        print(f"❌ لم يتم العثور على ملف البيانات في: {input_file}")

if __name__ == "__main__":
    analyze_all_clients()
