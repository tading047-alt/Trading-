import pandas as pd
import os

def generate_excel():
    # تحديد مسار المجلد (output) بشكل مطلق داخل الحاوية
    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(current_dir, 'output')
    
    # إنشاء المجلد إذا لم يكن موجوداً
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"📁 تم إنشاء المجلد: {output_dir}")

    # بيانات بسيطة للتجربة
    data = {
        'ID': [1, 2, 3, 4],
        'Product': ['Laptop', 'Mouse', 'Keyboard', 'Monitor'],
        'Price': [1200, 25, 45, 300],
        'Status': ['In Stock', 'Out of Stock', 'In Stock', 'In Stock']
    }

    df = pd.DataFrame(data)
    
    # المسار النهائي للملف
    file_path = os.path.join(output_dir, 'report.xlsx')
    
    # حفظ الملف
    df.to_excel(file_path, index=False)
    print(f"✅ تم توليد الملف بنجاح في: {file_path}")

if __name__ == "__main__":
    generate_excel()
