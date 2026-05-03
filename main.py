import pandas as pd
import os
import requests

# إعدادات تلغرام (يفضل وضعها في Environment Variables في Railway)
BOT_TOKEN = os.getenv('TELEGRAM_TOKEN', '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo')
CHAT_ID = os.getenv('CHAT_ID', '5067771509')

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    requests.post(url, data=payload)

def send_telegram_file(file_path):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    with open(file_path, 'rb') as file:
        requests.post(url, data={'chat_id': CHAT_ID}, files={'document': file})

def analyze_and_send():
    # مسار الملف الذي حملته في مجلد data
    input_file = 'data/Large_Sales_Purchases_Data.xlsx'
    output_file = 'output/final_analysis.xlsx'

    if not os.path.exists('output'):
        os.makedirs('output')

    if os.path.exists(input_file):
        print("📖 جاري تحميل البيانات في DataFrame...")
        df = pd.read_excel(input_file)

        # 1. تحليل أكثر العملاء تعاملاً (حسب إجمالي المبالغ)
        # نقوم بتجميع البيانات حسب اسم العميل وحساب مجموع الإجمالي
        top_clients = df.groupby('الجهة (عميل/مورد)')['الإجمالي'].sum().sort_values(ascending=False)
        
        # تجهيز نص الرسالة
        analysis_msg = "📊 *تقرير تحليل العملاء الأكثر تعاملاً:*\n\n"
        for client, total in top_clients.head(5).items():
            analysis_msg += f"👤 *{client}*: {total:,.2f} ريال/دولار\n"

        # 2. حفظ النتيجة في ملف جديد (اختياري)
        df.to_excel(output_file, index=False)

        # 3. إرسال النتيجة والملف إلى تلغرام
        print("🚀 جاري الإرسال إلى تلغرام...")
        send_telegram_msg(analysis_msg)
        send_telegram_file(input_file)
        
        print("✅ تمت العملية بنجاح!")
    else:
        print(f"❌ لم يتم العثور على الملف في: {input_file}")

if __name__ == "__main__":
    analyze_and_send()
