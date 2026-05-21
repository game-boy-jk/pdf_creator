# PDF Creator

FastAPI-сервис для заполнения PDF-шаблонов и сохранения результата в S3/MinIO.

Шаблоны — обычные PDF из Word или LibreOffice. Поля подстановки расставляются прямо в тексте документа.

## Структура проекта

```
app/
├── main.py        # FastAPI: роуты /health и /generate
├── config.py      # настройки из env или Spring Cloud Config
├── storage.py     # чтение/запись файлов в MinIO
├── schemas.py     # Pydantic-модели запроса и ответа
└── pdf/
    ├── __init__.py
    ├── filler.py  # основная логика: поиск и замена текста в PDF
    ├── fonts.py   # загрузка и кеширование шрифтов
    └── layout.py  # вычисление координат и стилей текста
```

## API

`POST /generate`

### Placeholder-ы

```json
{
  "template_id": "templates/contract.pdf",
  "data": {
    "customer_name": "OOO Romashka",
    "date": "2026-05-20",
    "total_sum": "12 500.00 RUB"
  }
}
```

Сервис найдёт в PDF `{{customer_name}}`, `{{date}}`, `{{total_sum}}` и подставит значения.

### Замена обычного текста

Для PDF без placeholder-ов:

```json
{
  "template_id": "templates/contract.pdf",
  "replace": {
    "Андрей": "Евгений"
  }
}
```

Заменяет все вхождения. `data` и `replace` можно комбинировать.

### Ответ

```json
{
  "file_id": "generated/<uuid>.pdf",
  "file_url": "http://localhost:9000/pdf-files/generated/<uuid>.pdf"
}
```

## Конфигурация

Обязательные переменные:

```env
MINIO_ENDPOINT=minio:9000
MINIO_PUBLIC_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=pdf-files
```

Необязательные:

```env
MINIO_SECURE=false
OUTPUT_PREFIX=generated/
CACHE_TTL_SEC=300

# TTF/OTF шрифт в том же bucket — нужен для кириллицы и subset-шрифтов
PDF_FONT_OBJECT_KEY=fonts/arial.ttf

# Spring Cloud Config (если используется)
CONFIG_SERVER_URL=http://config-server:8888
CONFIG_APP_NAME=pdf-creator
CONFIG_PROFILE=default
CONFIG_LABEL=main
CONFIG_FAIL_FAST=false
```

## Запуск

```bash
# Локально
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Docker
docker compose up --build
```

## Тесты

```bash
pytest -q
```
