import pandas as pd
import os
import requests

# إعدادات تلغرام (تأكد من ضبطها في Railway Variables)
BOT_TOKEN = os.getenv('TELEGRAM_TOKEN', '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo')
CHAT_ID = os.getenv('CHAT_ID', '5067771509')

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"❌ خطأ في إرسال الرسالة: {e}")

def send_telegram_file(file_path, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, 'rb') as file:
            payload = {'chat_id': CHAT_ID, 'caption': caption}
            files = {'document': file}
            requests.post(url, data=payload, files=files)
            print(f"🚀 تم إرسال {file_path} بنجاح!")
    except Exception as e:
        print(f"❌ خطأ في إرسال الملف: {e}")

def analyze_and_notify():
    input_file = 'data/Large_Sales_Purchases_Data.xlsx'
    output_file = 'output/complete_clients_stats.xlsx'

    if not os.path.exists('output'):
        os.makedirs('output')

    if os.path.exists(input_file):
        print("📖 جاري تحليل البيانات...")
        df = pd.read_excel(input_file)

        # تجميع البيانات لكل عميل
        stats = df.groupby('الجهة (عميل/مورد)').agg({
            'الإجمالي': 'sum',
            'رقم العملية': 'count'
        }).reset_index()
        stats.columns = ['العميل', 'إجمالي_المبالغ', 'عدد_المعاملات']
        
        # ترتيب البيانات
        stats_sorted = stats.sort_values(by='إجمالي_المبالغ', ascending=False)

        # 1. إعداد إشعار أفضل 3 عملاء
        top_3 = stats_sorted.head(3)
        msg_top = "🏆 *إشعار: أفضل 3 عملاء (الأعلى تعاملاً ماليًا):*\n\n"
        for _, row in top_3.iterrows():
            msg_top += f"🥇 *{row['العميل']}*: {row['إجمالي_المبالغ']:,.2f} ريال\n"
        
        # 2. إعداد إشعار أقل 3 عملاء
        bottom_3 = stats_sorted.tail(3).iloc[::-1] # عكس الترتيب ليظهر الأقل أولاً
        msg_bottom = "⚠️ *إشعار: أقل 3 عملاء تعاملاً:*\n\n"
        for _, row in bottom_3.iterrows():
            msg_bottom += f"👤 *{row['العميل']}*: {row['إجمالي_المبالغ']:,.2f} ريال\n"

        # حفظ الجدول الكامل
        stats_sorted.to_excel(output_file, index=False)

        # --- الإرسال إلى تلغرام بالترتيب المطلوب ---
        print("📤 جاري إرسال التنبيهات والجدول...")
        
        # إرسال الإشعار الأول
        send_telegram_msg(msg_top)
        
        # إرسال الإشعار الثاني
        send_telegram_msg(msg_bottom)
        
        # إرسال الجدول الكامل
        send_telegram_file(output_file, "📊 التقرير الختامي لإحصائيات جميع العملاء")
        
        print("✅ تمت العملية بنجاح!")
    else:
        print(f"❌ الملف غير موجود: {input_file}")

if __name__ == "__main__":
    analyze_and_notify()
