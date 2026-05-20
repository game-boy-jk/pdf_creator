# PDF Creator

FastAPI-сервис для заполнения PDF-шаблонов и сохранения готовых PDF в S3/MinIO.

Шаблоны - это обычные PDF-файлы, экспортированные из Word, LibreOffice и других редакторов. Сервис не создает шаблоны в коде: нужные поля надо заранее поставить прямо в тексте документа.

Пример шаблона:

```text
Contract with {{customer_name}}
Date: {{date}}
Total: {{total_sum}}
```

## API

`POST /generate`

### Заполнение placeholder-ов

Для новых шаблонов лучше использовать поля вида `{{name}}`, `{{date}}`, `{{total_sum}}`.

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

Сервис найдет в PDF:

```text
{{customer_name}}
{{date}}
{{total_sum}}
```

и подставит значения из `data`.

### Замена обычного текста

Для старых PDF без placeholder-ов можно использовать `replace`.

Пример: в PDF уже есть текст `Андрей`, его нужно заменить на `Евгений`.

```json
{
  "template_id": "templates/replace-greeting.pdf",
  "replace": {
    "Андрей": "Евгений"
  }
}
```

Если слово встречается несколько раз, сервис заменит все найденные вхождения в текстовом слое PDF.

`data` и `replace` можно использовать вместе:

```json
{
  "template_id": "templates/contract.pdf",
  "data": {
    "customer_name": "OOO Romashka",
    "date": "2026-05-20",
    "total_sum": "12 500.00 RUB"
  },
  "replace": {
    "Андрей": "Евгений"
  }
}
```

Для новых шаблонов предпочтительнее `data` с placeholder-ами. `replace` полезен для старых или уже готовых PDF, где нельзя быстро расставить `{{...}}`.

### Ответ

```json
{
  "file_id": "generated/<uuid>.pdf",
  "file_url": "http://localhost:9000/pdf-files/generated/<uuid>.pdf"
}
```

`file_id` генерируется сервисом.

## Конфигурация

Обязательные переменные:

```env
MINIO_ENDPOINT=minio:9000
MINIO_PUBLIC_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=pdf-files
```

Необязательные переменные:

```env
MINIO_SECURE=false
OUTPUT_PREFIX=generated/
CACHE_TTL_SEC=300
PDF_FONT_OBJECT_KEY=fonts/arial.ttf
CONFIG_SERVER_URL=http://config-server:8888
CONFIG_APP_NAME=pdf-creator
CONFIG_PROFILE=default
CONFIG_LABEL=main
CONFIG_FAIL_FAST=false
```

`PDF_FONT_OBJECT_KEY` должен указывать на TTF/OTF-шрифт в том же bucket. Это важно, если шаблоны используют subset-шрифты или в PDF нужно вставлять кириллицу.

## Запуск

Локально:

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Через Docker:

```bash
docker compose up --build
```

## Тесты

```bash
pytest -q
```
