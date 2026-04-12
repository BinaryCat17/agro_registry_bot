# Агро-реестр бот (Agro Registry Bot)

Локальная копия официального реестра пестицидов и агрохимикатов Минсельхоза России с возможностью поиска через SQL и Python API.

## Структура

- `data/reestr.db` — SQLite база данных реестра
- `src/importer.py` — загрузка и парсинг XML с `opendata.mcx.ru`
- `src/database.py` — класс `RegistryDatabase` для работы с БД
- `query.py` — CLI-утилита для быстрых SQL-запросов
- `update_db.py` — скрипт полного обновления базы

## Использование

### Обновить базу

```bash
python update_db.py
```

### Выполнить SQL-запрос

```bash
python query.py "SELECT * FROM pestitsidy WHERE naimenovanie REGEXP 'престиж' LIMIT 3"
```

### Использовать в Python

```python
from src.database import RegistryDatabase

db = RegistryDatabase()

# Поиск пестицида по названию
results = db.find_pesticide_by_name("престиж")

# Поиск по действующему веществу
results = db.find_pesticide_by_dv("имидаклоприд")

# Поиск по культуре
results = db.search_pesticides_by_crop("пшеница озимая")

# Регламенты применения конкретного препарата
apps = db.find_pesticide_applications("019-01-2400-1")
```

## Таблицы

### Пестициды

- `pestitsidy` — основные сведения о препаратах
  - `nomer_reg` — номер государственной регистрации
  - `naimenovanie` — торговое название
  - `deystvuyushchee_veshchestvo` — JSON массив ДВ с концентрациями
  - `registrant` — регистратор
  - `status` — статус регистрации
  - `srok_reg` — срок действия регистрации
  - `preparativnaya_forma` — препаративная форма
  - `klass_opasnosti` — класс опасности

- `pestitsidy_primeneniya` — регламенты применения
  - `nomer_reg` — FK
  - `kultura` — культура / объект обработки
  - `vrednyy_obekt` — вредный объект / назначение
  - `sposob` — способ и время обработки
  - `norma` — норма применения
  - `srok_ozhidaniya` — срок ожидания
  - `vyhod` — сроки выхода для работ
  - `osobennosti` — особенности применения

### Агрохимикаты

- `agrokhimikaty` — основные сведения
  - `rn` — номер регистрации
  - `preparat` — название препарата
  - `registrant` — регистратор
  - `status` — статус
  - `srok_reg` — срок действия
  - `group_name` — группа

- `agrokhimikaty_primeneniya` — регламенты применения
  - `rn` — FK
  - `kultura` — культура
  - `marka` — марка / вид
  - `oblast` — область применения
  - `doza` — доза применения
  - `vremya` — время применения
  - `osobennosti` — особенности

## Особенности

- Поддержка `REGEXP` в SQLite (регистронезависимый поиск по кириллице)
- Поле `deystvuyushchee_veshchestvo` хранится как JSON и может быть разобрано через `json_each()` в SQL
- База обновляется из официальных открытых данных Минсельхоза
