import pandas as pd
import asyncio
from telegram import Bot

# دالة محدثة لإرسال النص والملف معاً
async def send_telegram_report_with_file(results_dict):
    token = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
    chat_id = 'YOUR_CHAT_ID'
    bot = Bot(token=token)
    
    # 1. تحويل النتائج إلى DataFrame وحفظها كـ CSV
    df_results = pd.DataFrame(list(results_dict.items()), columns=['Symbol', 'Profit_Percentage'])
    # ترتيب النتائج من الأعلى ربحاً للأقل
    df_results = df_results.sort_values(by='Profit_Percentage', ascending=False)
    
    file_name = "backtest_results.csv"
    df_results.to_csv(file_name, index=False)
    
    # 2. تجهيز رسالة نصية ملخصة لأفضل 5 عملات
    summary = "✅ انتهى فحص 300 عملة\n\n"
    summary += "🔝 أفضل 5 نتائج:\n"
    for index, row in df_results.head(5).iterrows():
        summary += f"💰 {row['Symbol']}: {row['Profit_Percentage']}%\n"
    
    # 3. إرسال النص
    await bot.send_message(chat_id=chat_id, text=summary)
    
    # 4. إرسال ملف CSV
    with open(file_name, 'rb') as file:
        await bot.send_document(chat_id=chat_id, document=file, caption="التقرير الكامل لجميع العملات 📄")

# ملاحظة: يتم استدعاء هذه الدالة في نهاية حلقة الفحص (Loop)
