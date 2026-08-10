import re

def clean_brand_name(value):
    value = str(value).replace('\xa0', ' ').strip().lower()
    value = value.replace('ё', 'е')

    # Убираем всё в круглых скобках
    value = re.sub(r'\s*\([^)]*\)', '', value)

    # Убираем лишние пробелы
    value = re.sub(r'\s+', ' ', value).strip()

    return value