# АгроРеестр Бот

Поиск по государственному реестру пестицидов и агрохимикатов Минсельхоза РФ.

## Быстрый старт

```bash
# 1. Клонировать репозиторий
git clone https://github.com/BinaryCat17/agro_registry_bot.git
cd agro_registry_bot

# 2. Создать виртуальное окружение
python3 -m venv .venv
source .venv/bin/activate

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Скопировать и настроить .env
cp .env.example .env
# Отредактировать .env - указать YANDEX_CLIENT_ID, YANDEX_CLIENT_SECRET, ADMIN_EMAIL

# 5. Инициализировать базу данных
python3 -c "from src.importer import run_import; run_import()"

# 6. Запустить классификацию
python3 scripts/classify.py
python3 scripts/classify_crop_groups.py

# 7. Запустить веб-сервер
python3 web/main.py
```

## Структура проекта

```
.
├── data/                  # База данных и XML-файлы
│   ├── reestr.db         # SQLite база
│   ├── agrokhimikaty.xml # Исходные данные
│   └── pestitsidy.xml
├── scripts/              # Скрипты обработки
│   ├── classify.py              # Классификация классов/методов
│   ├── classify_crop_groups.py  # Назначение групп культур
│   ├── rebuild_crops.py         # Перестройка тегов культур
│   └── auto_update.sh           # Автообновление (cron)
├── src/                  # Исходный код
│   ├── crop_parser.py    # Парсер культур
│   ├── crop_hierarchy.py # Иерархия культур
│   ├── importer.py       # Импорт из XML
│   └── database.py       # Работа с БД
├── web/                  # Веб-интерфейс
│   ├── main.py           # FastAPI backend
│   └── static/           # Frontend (Vue.js)
└── backups/              # Автоматические бэкапы
```

## Скрипты обработки данных

Все изменения базы данных автоматизированы через скрипты:

| Скрипт | Назначение |
|--------|-----------|
| `scripts/classify.py` | Классификация препаратов по классу (фунгицид, инсектицид...) и методу применения |
| `scripts/classify_crop_groups.py` | Назначение групп культур (зерновые, бобовые...) |
| `scripts/rebuild_crops.py` | Перестройка тегов культур из сырых данных |
| `src/importer.py` | Загрузка свежих данных из XML Минсельхоза |

## Автообновление базы данных

Настройка автоматического обновления каждую ночь в полночь:

```bash
# Открыть crontab
crontab -e

# Добавить строку:
0 0 * * * /path/to/agro_registry_bot/scripts/auto_update.sh
```

Скрипт `auto_update.sh` выполняет:
1. Бэкап текущей базы (сохраняет 10 последних)
2. Загрузку свежих XML с сайта Минсельхоза
3. Пересоздание таблиц
4. Классификацию всех данных
5. Логирование в `auto_update.log`

## Обновление вручную

```bash
cd /path/to/agro_registry_bot
source .venv/bin/activate

# 1. Загрузить свежие данные
python3 -c "from src.importer import run_import; run_import()"

# 2. Переклассифицировать
python3 scripts/classify.py
python3 scripts/classify_crop_groups.py

# 3. Перезапустить сервер
pkill -f "python3 web/main.py"
python3 web/main.py
```

## Переменные окружения (.env)

```bash
# Обязательные (Yandex OAuth для админки)
YANDEX_CLIENT_ID=your_client_id
YANDEX_CLIENT_SECRET=your_client_secret
ADMIN_EMAIL=admin@example.com
PUBLIC_HOST=https://your-domain.com
SESSION_SECRET=random-secret-key

# Опциональные (для AI-чата)
GEMINI_API_KEY=
OPENAI_API_KEY=
```

## Лицензия

MIT
