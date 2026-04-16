#!/bin/bash
# update.sh - Единый скрипт обновления базы данных агрохимикатов
# Выполняет: парсинг реестра Минсельхоза → классификацию → создание групп культур

set -euo pipefail

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Директория проекта
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$PROJECT_DIR/data"
BACKUP_DIR="$PROJECT_DIR/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo -e "${YELLOW}=== Обновление базы данных реестра Минсельхоза ===${NC}"
echo "Время: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Создаем бэкап перед обновлением
echo -e "${YELLOW}[1/5] Создание бэкапа...${NC}"
mkdir -p "$BACKUP_DIR"
if [ -f "$DATA_DIR/reestr.db" ]; then
    cp "$DATA_DIR/reestr.db" "$BACKUP_DIR/reestr_${TIMESTAMP}.db"
    echo -e "${GREEN}✓ Бэкап создан: $BACKUP_DIR/reestr_${TIMESTAMP}.db${NC}"
else
    echo -e "${YELLOW}! База данных не найдена, пропускаем бэкап${NC}"
fi
echo ""

# Обновление данных с сервера Минсельхоза
echo -e "${YELLOW}[2/5] Парсинг реестра Минсельхоза...${NC}"
cd "$PROJECT_DIR"
if [ -f "scripts/parse_reestr.py" ]; then
    python3 scripts/parse_reestr.py
    echo -e "${GREEN}✓ Данные обновлены${NC}"
else
    echo -e "${RED}✗ Скрипт parse_reestr.py не найден${NC}"
    exit 1
fi
echo ""

# Классификация препаратов
echo -e "${YELLOW}[3/5] Классификация препаратов...${NC}"
python3 scripts/classify.py
echo -e "${GREEN}✓ Классификация завершена${NC}"
echo ""

# Создание групп культур
echo -e "${YELLOW}[4/5] Создание групп культур...${NC}"
python3 scripts/classify_crop_groups.py
echo -e "${GREEN}✓ Группы культур созданы${NC}"
echo ""

# Проверка корректности
echo -e "${YELLOW}[5/5] Проверка корректности...${NC}"
python3 << 'PYEOF'
import sqlite3
import sys

conn = sqlite3.connect('data/reestr.db')
c = conn.cursor()

# Проверяем Каспера
c.execute("""
    SELECT t.name FROM product_tags pt 
    JOIN tags t ON pt.tag_id = t.id 
    JOIN pestitsidy p ON p.id = pt.product_id
    WHERE p.naimenovanie LIKE '%Каспер%' AND t.category = 'crop'
""")
kasper_crops = [row[0] for row in c.fetchall()]
print(f"  Каспер: {len(kasper_crops)} культур - {', '.join(kasper_crops)}")

# Проверяем Ланцею
c.execute("""
    SELECT t.name FROM product_tags pt 
    JOIN tags t ON pt.tag_id = t.id 
    JOIN pestitsidy p ON p.id = pt.product_id
    WHERE p.naimenovanie LIKE '%Ланцея%' AND t.category = 'class'
""")
lancea_class = [row[0] for row in c.fetchall()]
print(f"  Ланцея: класс - {', '.join(lancea_class)}")

# Считаем статистику
c.execute("SELECT COUNT(*) FROM pestitsidy")
pest_count = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM agrokhimikaty")
agro_count = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM product_tags WHERE product_type = 'pesticide'")
pest_tags = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM product_tags WHERE product_type = 'agrochemical'")
agro_tags = c.fetchone()[0]

print(f"\n  Статистика:")
print(f"    Пестициды: {pest_count}")
print(f"    Агрохимикаты: {agro_count}")
print(f"    Теги пестицидов: {pest_tags}")
print(f"    Теги агрохимикатов: {agro_tags}")

conn.close()
PYEOF

echo -e "${GREEN}✓ Проверка завершена${NC}"
echo ""

echo -e "${GREEN}=== Обновление успешно завершено! ===${NC}"
echo "Бэкап: $BACKUP_DIR/reestr_${TIMESTAMP}.db"
