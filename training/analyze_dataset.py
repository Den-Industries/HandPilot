"""
Анализатор датасета жестов (исключая класс None).
Читает все CSV из папки и выводит распределение классов в консоли.
"""

import os
import sys
import pandas as pd
from collections import Counter

# ------------------------------------------------------------
# Правильное сопоставление кодов → символы
# ------------------------------------------------------------
cp1251_to_unicode = {
    224: 'а', 225: 'б', 226: 'в', 227: 'г', 228: 'д', 229: 'е',
    230: 'ж', 231: 'з', 232: 'и', 233: 'й', 234: 'к', 235: 'л',
    236: 'м', 237: 'н', 238: 'о', 239: 'п', 240: 'р', 241: 'с',
    242: 'т', 243: 'у', 244: 'ф', 245: 'х', 246: 'ц', 247: 'ч',
    248: 'ш', 249: 'щ', 250: 'ъ', 251: 'ы', 252: 'ь', 253: 'э',
    254: 'ю', 255: 'я'
}

CLASSES = {}
CLASSES.update(cp1251_to_unicode)
CLASSES.update({49: '1', 50: '2', 51: '3', 52: '4', 53: '5'})
CLASSES[76] = 'Like'     # L
CLASSES[68] = 'Dislike'  # D
CLASSES[32] = 'None'     # пробел (будет исключён)

# ------------------------------------------------------------
def load_all_csvs(directory):
    csv_files = [f for f in os.listdir(directory) if f.endswith('.csv')]
    if not csv_files:
        print(f"Нет CSV-файлов в папке '{directory}'")
        sys.exit(1)
    dfs = []
    for file in csv_files:
        path = os.path.join(directory, file)
        try:
            df = pd.read_csv(path)
            dfs.append(df)
        except Exception as e:
            print(f"Ошибка при чтении {file}: {e}")
    if not dfs:
        print("Не удалось загрузить ни одного CSV")
        sys.exit(1)
    return pd.concat(dfs, ignore_index=True)

def analyze(df):
    counter = Counter(df['Target'])

    # Исключаем класс None (код 32) из статистики
    # Закомментируй следующую строку, если хочешь видеть None в отчёте
    if 32 in counter:
        del counter[32]

    total = sum(counter.values())
    num_classes = len(counter)
    if total == 0:
        print("Нет данных для отображения (возможно, все примеры — None).")
        return

    sorted_counts = counter.most_common()
    max_count = sorted_counts[0][1]

    BAR_WIDTH = 50

    print("\n" + "=" * 80)
    print("           РАСПРЕДЕЛЕНИЕ КЛАССОВ В ДАТАСЕТЕ (без None)")
    print("=" * 80)
    print(f"Всего примеров (без None): {total}")
    print(f"Количество классов: {num_classes}")
    print(f"Среднее на класс: {total / num_classes:.1f}")
    print(f"Медиана на класс: {sorted_counts[len(sorted_counts)//2][1]}")
    print(f"Мин./Макс. примеров: {sorted_counts[-1][1]} / {max_count}")
    print("=" * 80)
    print(f"{'Класс':<10} {'Код':<6} {'Кол-во':<8} {'Процент':<8} {'Гистограмма'}")
    print("-" * 80)

    for code, count in sorted_counts:
        name = CLASSES.get(code, f"код{code}")
        percent = (count / total) * 100
        bar_len = int((count / max_count) * BAR_WIDTH) if max_count > 0 else 0
        bar = '█' * bar_len
        print(f"{name:<10} {code:<6} {count:<8} {percent:5.1f}%   {bar}")

    print("=" * 80)

    # Пропущенные классы (кроме None)
    all_expected = set(CLASSES.keys()) - {32}
    missing = all_expected - set(counter.keys())
    if missing:
        print("\nКлассы, отсутствующие в датасете:")
        for code in sorted(missing):
            name = CLASSES[code]
            print(f"  {name} (код {code})")
    else:
        print("\nВсе ожидаемые классы (кроме None) присутствуют в датасете.")

if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "datasets")
    if not os.path.isdir(data_dir):
        print(f"Папка '{data_dir}' не найдена. Укажите существующую папку с CSV.")
        sys.exit(1)

    print(f"Анализ CSV из папки: {data_dir}")
    df = load_all_csvs(data_dir)
    analyze(df)