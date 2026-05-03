import pandas as pd
import os
import requests
import matplotlib.pyplot as plt

# إعدادات تلغرام
BOT_TOKEN = os.getenv('TELEGRAM_TOKEN', '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo')
CHAT_ID = os.getenv('CHAT_ID', '5067771509')

def send_telegram_photo(photo_path, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(photo_path, 'rb') as photo:
        requests.post(url, data={'chat_id': CHAT_ID, 'caption': caption}, files={'photo': photo})

def analyze_and_draw():
    input_file = 'data/Large_Sales_Purchases_Data.xlsx'
    chart_path = 'output/transactions_distribution.png'
    
    if not os.path.exists('output'): os.makedirs('output')

    if os.path.exists(input_file):
        df = pd.read_excel(input_file)
        stats = df.groupby('الجهة (عميل/مورد)').agg({'رقم العملية': 'count'}).reset_index()
        stats.columns = ['العميل', 'عدد_المعاملات']

        # إنشاء الرسم البياني
        plt.figure(figsize=(8, 8))
        plt.pie(stats['عدد_المعاملات'], labels=stats['الالعميل'], 
                autopct=lambda p: '{:.0f}'.format(p * sum(stats['عدد_المعاملات']) / 100),
                startangle=140, pctdistance=0.85)
        
        # تحويلها لدائرة مفرغة (Donut)
        centre_circle = plt.Circle((0,0), 0.70, fc='white')
        plt.gcf().gca().add_artist(centre_circle)
        
        # إضافة الرقم الإجمالي في المنتصف
        total_transactions = stats['عدد_المعاملات'].sum()
        plt.text(0, 0, f'المعاملات\n{total_transactions}', ha='center', va='center', fontsize=14, fontweight='bold')
        
        plt.title('توزيع عدد المعاملات لكل عميل')
        plt.savefig(chart_path)
        plt.close()

        # إرسال الصورة إلى تلغرام
        send_telegram_photo(chart_path, "📊 رسم بياني لتوزيع عدد المعاملات")
        print("✅ تم إرسال الرسم البياني!")

if __name__ == "__main__":
    analyze_and_draw()
