import pandas as pd
import os
import requests

# إعدادات تلغرام
BOT_TOKEN = 'YOUR_BOT_TOKEN'
CHAT_ID = 'YOUR_CHAT_ID'

def send_to_telegram(file_path):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, 'rb') as file:
            payload = {'chat_id': CHAT_ID, 'caption': '✅ تم معالجة الملف بنجاح!'}
            files = {'document': file}
            response = requests.post(url, data=payload, files=files)
            if response.status_code == 200:
                print("🚀 تم إرسال الملف إلى تلغرام بنجاح!")
            else:
                print(f"❌ فشل الإرسال: {response.text}")
    except Exception as e:
        print(f"❌ خطأ أثناء الإرسال: {e}")

def process():
    input_file = 'data/data_results.xlsx'
    output_dir = 'output'
    output_file = os.path.join(output_dir, 'final_result.xlsx')

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    if os.path.exists(input_file):
        print("📖 جاري معالجة الملف...")
        df = pd.read_excel(input_file)
        
        # حفظ الملف محلياً في خادم Railway مؤقتاً
        df.to_excel(output_file, index=False)
        
        # إرسال الملف إلى تلغرام
        send_to_telegram(output_file)
    else:
        print(f"❌ الملف غير موجود في: {input_file}")

if __name__ == "__main__":
    process()
