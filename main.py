import pandas as pd
import os
import requests
import matplotlib.pyplot as plt
import arabic_reshaper
from bidi.algorithm import get_display

# إعدادات تلغرام
BOT_TOKEN = os.getenv('TELEGRAM_TOKEN', '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo')
CHAT_ID = os.getenv('CHAT_ID', '5067771509')

def fix_arabic_text(text):
    # دالة لمعالجة النصوص العربية لتظهر بشكل صحيح في الرسم البياني
    reshaped_text = arabic_reshaper.reshape(text)
    return get_display(reshaped_text)

def send_telegram_photo(photo_path, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(photo_path, 'rb') as photo:
        requests.post(url, data={'chat_id': CHAT_ID, 'caption': caption}, files={'photo': photo})

def analyze_and_plot():
    input_file = 'data/Large_Sales_Purchases_Data.xlsx'
    output_hist = 'output/clients_histogram.png'
    
    if not os.path.exists('output'): os.makedirs('output')

    if os.path.exists(input_file):
        df = pd.read_excel(input_file)
        df.columns = df.columns.str.strip()
        
        # تجميع البيانات (إجمالي المبالغ لكل عميل)
        stats = df.groupby('الجهة (عميل/مورد)')['الإجمالي'].sum().reset_index()
        stats.columns = ['العميل', 'إجمالي_المبالغ']
        stats = stats.sort_values(by='إجمالي_المبالغ', ascending=False)

        # تجهيز الأسماء العربية للرسم البياني
        stats['العميل_معدل'] = stats['العميل'].apply(fix_arabic_text)

        # رسم الـ Histogram (Bar Chart)
        plt.figure(figsize=(12, 7))
        bars = plt.bar(stats['العميل_معدل'], stats['إجمالي_المبالغ'], color='skyblue', edgecolor='navy')
        
        # إضافة العناوين مع معالجة اللغة العربية
        plt.title(fix_arabic_text('إجمالي قيمة المعاملات لكل عميل'), fontsize=16)
        plt.xlabel(fix_arabic_text('اسم العميل'), fontsize=12)
        plt.ylabel(fix_arabic_text('إجمالي المبالغ'), fontsize=12)
        
        # تدوير الأسماء لتسهيل القراءة إذا كانت كثيرة
        plt.xticks(rotation=45, ha='right')

        # إضافة القيم فوق كل عمود
        for bar in bars:
            yval = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2, yval, f'{yval:,.0f}', va='bottom', ha='center', fontsize=10)

        plt.tight_layout()
        plt.savefig(output_hist)
        plt.close()

        # إرسال الصورة إلى تلغرام
        send_telegram_photo(output_hist, "📊 مخطط بياني (Histogram) لقيم معاملات العملاء")
        print("✅ تم إرسال المخطط البياني بنجاح!")

if __name__ == "__main__":
    analyze_and_plot()
