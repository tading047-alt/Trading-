import pandas as pd
import os

# التأكد من وجود المجلد
output_dir = 'output'
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# إنشاء بيانات بسيطة
data = {
    'الاسم': ['أحمد', 'سارة', 'خالد', 'ليلى'],
    'المهنة': ['مطور', 'مصممة', 'محلل بيانات', 'مديرة مشاريع'],
    'الراتب': [5000, 6000, 5500, 7000]
}

df = pd.DataFrame(data)

# حفظ الملف
file_path = os.path.join(output_dir, 'data_results.xlsx')
df.to_excel(file_path, index=False)

print(f"✅ تم حفظ الملف بنجاح في: {file_path}")
