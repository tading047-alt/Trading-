import pandas as pd
import os
import sys

def process():
    # المسارات داخل الحاوية
    input_file = '/app/data/data_results.xlsx'
    output_dir = '/app/output'
    output_file = os.path.join(output_dir, 'final_result.xlsx')

    print("--- بدأت العملية ---")

    # 1. التأكد من وجود ملف المدخلات
    if not os.path.exists(input_file):
        print(f"❌ خطأ: لم أجد ملف المدخلات في: {input_file}")
        print("تأكد من وضع ملف data_results.xlsx داخل مجلد data على جهازك.")
        return

    try:
        # 2. قراءة الملف
        print(f"📖 جاري قراءة الملف من {input_file}...")
        df = pd.read_excel(input_file)
        
        # 3. التأكد من وجود مجلد المخرجات
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"📁 تم إنشاء مجلد المخرجات: {output_dir}")

        # 4. حفظ الملف
        df.to_excel(output_file, index=False)
        print(f"✅ تم حفظ الملف بنجاح في: {output_file}")
        print("--- انتهت العملية بنجاح ---")

    except Exception as e:
        print(f"❌ حدث خطأ غير متوقع: {e}")

if __name__ == "__main__":
    process()
