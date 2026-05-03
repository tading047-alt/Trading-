import pandas as pd
import os

def process_excel():
    # المسارات داخل الحاوية
    input_file = '/app/data/data_results.xlsx'
    output_dir = '/app/output'
    output_file = os.path.join(output_dir, 'final_result.xlsx')

    print("--- بدأت العملية ---")

    # التأكد من وجود ملف المدخلات
    if not os.path.exists(input_file):
        print(f"❌ خطأ: لم يتم العثور على ملف: {input_file}")
        print("تأكد من وجود مجلد 'data' وبداخله ملف 'data_results.xlsx'")
        return

    try:
        # قراءة الملف
        print(f"📖 جاري قراءة الملف...")
        df = pd.read_excel(input_file)

        # إنشاء مجلد المخرجات إذا لم يكن موجوداً
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # حفظ الملف الجديد
        df.to_excel(output_file, index=False)
        print(f"✅ تم حفظ الملف بنجاح في: {output_file}")
        print("--- انتهت العملية بنجاح ---")

    except Exception as e:
        print(f"❌ حدث خطأ: {e}")

if __name__ == "__main__":
    process_excel()
