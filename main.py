import pandas as pd
import os

# المسارات
input_path = os.path.join('data', 'data_results.xlsx')
output_dir = 'output'
output_path = os.path.join(output_dir, 'data_results_processed.xlsx')

def process_file():
    # 1. التأكد من وجود مجلد المخرجات
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # 2. التأكد من وجود ملف المدخلات
    if not os.path.exists(input_path):
        print(f"❌ خطأ: الملف غير موجود في المسار: {input_path}")
        return

    try:
        # 3. قراءة الملف
        df = pd.read_excel(input_path)
        print("📖 تم قراءة الملف بنجاح.")

        # يمكنك إضافة أي تعديلات على البيانات هنا (مثلاً: df['جديد'] = 'قيمة')
        
        # 4. حفظ الملف في مجلد المخرجات
        df.to_excel(output_path, index=False)
        print(f"✅ تم حفظ الملف بنجاح في: {output_path}")

    except Exception as e:
        print(f"❌ حدث خطأ أثناء المعالجة: {e}")

if __name__ == "__main__":
    process_file()
