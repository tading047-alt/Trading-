import pandas as pd
import os
import requests
import matplotlib.pyplot as plt

# إعدادات تلغرام - يفضل ضبطها في Railway Variables
# إذا وضعتها هنا مباشرة، استبدل النص بالقيم الحقيقية
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
    except Exception as e:
        print(f"❌ خطأ في إرسال الملف: {e}")

def send_telegram_photo(photo_path, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as photo:
            payload = {'chat_id': CHAT_ID, 'caption': caption}
            files = {'photo': photo}
            requests.post(url, data=payload, files=files)
    except Exception as e:
        print(f"❌ خطأ في إرسال الصورة: {e}")

def analyze_data():
    input_file = 'data/Large_Sales_Purchases_Data.xlsx'
    output_xlsx = 'output/final_clients_report.xlsx'
    output_chart = 'output/transactions_chart.png'

    if not os.path.exists('output'):
        os.makedirs('output')

    if not os.path.exists(input_file):
        print(f"❌ الملف غير موجود في المسار: {input_file}")
        return

    try:
        # 1. قراءة الملف وتنظيف أسماء الأعمدة لتجنب خطأ KeyError
        df = pd.read_excel(input_file)
        df.columns = df.columns.str.strip()

        # تحديد الأعمدة برمجياً لتجنب مشاكل الأسماء
        col_entity = 'الجهة (عميل/مورد)'
        col_total = 'الإجمالي'
        col_id = 'رقم العملية'

        # التحقق من وجود الأعمدة
        if col_entity not in df.columns:
            send_telegram_msg(f"❌ خطأ: لم أجد عمود '{col_entity}'. الأعمدة المتوفرة: {list(df.columns)}")
            return

        # 2. تحليل البيانات (الإحصائيات)
        stats = df.groupby(col_entity).agg({
            col_total: 'sum',
            col_id: 'count'
        }).reset_index()
        stats.columns = ['العميل', 'إجمالي_المبالغ', 'عدد_المعاملات']
        stats_sorted = stats.sort_values(by='إجمالي_المبالغ', ascending=False)

        # 3. إعداد رسائل التنبيه (أفضل 3 وأقل 3)
        top_3 = stats_sorted.head(3)
        bottom_3 = stats_sorted.tail(3).iloc[::-1]

        msg_top = "🏆 *أفضل 3 عملاء (الأعلى مبيعاً):*\n\n"
        for _, row in top_3.iterrows():
            msg_top += f"🥇 *{row['العميل']}*: {row['إجمالي_المبالغ']:,.2f}\n"

        msg_bottom = "⚠️ *أقل 3 عملاء تعاملاً:*\n\n"
        for _, row in bottom_3.iterrows():
            msg_bottom += f"👤 *{row['العميل']}*: {row['إجمالي_المبالغ']:,.2f}\n"

        # 4. إنشاء الرسم البياني الدائري (Donut Chart)
        plt.figure(figsize=(8, 8))
        plt.pie(stats['عدد_المعاملات'], labels=stats['العميل'], 
                autopct=lambda p: '{:.0f}'.format(p * sum(stats['عدد_المعاملات']) / 100),
                startangle=140, pctdistance=0.80)
        
        centre_circle = plt.Circle((0,0), 0.65, fc='white')
        plt.gcf().gca().add_artist(centre_circle)
        
        total_tx = stats['عدد_المعاملات'].sum()
        plt.text(0, 0, f'إجمالي\n{total_tx}\nمعاملة', ha='center', va='center', fontsize=12, fontweight='bold')
        
        plt.title('توزيع المعاملات لكل عميل')
        plt.savefig(output_chart, bbox_inches='tight')
        plt.close()

        # 5. حفظ الجدول النهائي
        stats_sorted.to_excel(output_xlsx, index=False)

        # 6. الإرسال إلى تلغرام بالترتيب
        send_telegram_msg(msg_top)
        send_telegram_msg(msg_bottom)
        send_telegram_photo(output_chart, "📊 رسم بياني لتوزيع عدد المعاملات")
        send_telegram_file(output_xlsx, "📑 التقرير التفصيلي لجميع العملاء")

        print("✅ تم تنفيذ كافة العمليات وإرسالها لتلغرام بنجاح!")

    except Exception as e:
        error_msg = f"❌ حدث خطأ أثناء المعالجة: {str(e)}"
        print(error_msg)
        send_telegram_msg(error_msg)

if __name__ == "__main__":
    analyze_data()
