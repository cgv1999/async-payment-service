# async-payment-service

Асинхронный микросервис процессинга платежей.

Принимает запросы на оплату, обрабатывает через эмулированный платежный шлюз и уведомляет клиента через webhook.

Все события публикуются надежно через Outbox pattern.

## Стек

- FastAPI + Pydantic v2 - HTTP API

- SQLAlchemy 2.0 (async) + asyncpg - работа с БД

- PostgreSQL 16 - хранилище платежей и outbox

- RabbitMQ 3.13 + FastStream - брокер сообщений

- Alembic - миграции

- Docker + docker-compose - запуск окружения

## Начало работы

Скопировать .env.example в .env:

```
cp .env.example .env
```

Запустить все одной командой:

```
docker compose up -d --build
```

Доступные сервисы:

- API + Swagger: http://localhost:8000/docs

- RabbitMQ UI: http://localhost:15672 (guest / guest)

- PostgreSQL: localhost:5432 (payment / payment)

Остановить:

```
docker compose down
```

Остановить и удалить данные:

```
docker compose down -v
```

## Как это работает

## Поток данных

1. Клиент отправляет POST на /api/v1/payments с заголовками X-API-Key и Idempotency-Key.

2. FastAPI в одной транзакции:

- создает запись в таблице payments со статусом pending;

- создает запись в таблице outbox со статусом pending.

3. Фоновый воркер outbox_publisher читает outbox и публикует событие в RabbitMQ.

4. Consumer получает сообщение из очереди payments.new:

- эмулирует обработку шлюза (2-5 секунд, 90% успех);

- обновляет статус платежа в БД;

- отправляет webhook на URL клиента.

5. Если webhook не доставлен после 3 попыток - сообщение публикуется в payments.new.dlq через exchange payments.dlx.

## Outbox pattern

Гарантирует, что событие не потеряется, если RabbitMQ временно недоступен. Запись в outbox идет в одной транзакции с записью в payments. Публикация в RabbitMQ происходит отдельно, а признак успешной публикации - поле published_at.

## Идемпотентность

Заголовок Idempotency-Key обязателен. По нему стоит уникальный индекс. При повторном запросе с тем же ключом возвращается тот же payment_id, новый платеж не создается.

## Retry и DLQ

Webhook повторяется 3 раза с экспоненциальной задержкой: 2, 4, 8 секунд. После трех неудач сообщение отправляется в Dead Letter Queue.

## Примеры API

## Создание платежа

Запрос:

```
curl -X POST http://localhost:8000/api/v1/payments \
  -H "Content-Type: application/" \
  -H "X-API-Key: secret-api-key-change-me" \
  -H "Idempotency-Key: order-12345" \
  -d '{
    "amount": "100.50",
    "currency": "RUB",
    "description": "Оплата заказа",
    "meta": {"order_id": 12345},
    "webhook_url": "https://webhook.site/your-unique-url"
  }'
```
  
Ответ:

```
{
  "payment_id": "f334ce23-5e1b-4abc-bb6b-383029e86d7a",
  "status": "pending",
  "created_at": "2026-10-05T15:39:55.816642Z"
}
```

## Получение платежа

```
curl http://localhost:8000/api/v1/payments/f334ce23-5e1b-4abc-bb6b-383029e86d7a \
  -H "X-API-Key: secret-api-key-change-me"
```

## Что приходит на webhook

```
{
  "payment_id": "f334ce23-5e1b-4abc-bb6b-383029e86d7a",
  "status": "succeeded",
  "amount": "100.50",
  "currency": "RUB",
  "processed_at": "2026-10-05T15:39:58.816642Z"
}
```

## Модель данных

## Таблица payments

- id - UUID, первичный ключ
  
- amount - сумма, Numeric(18, 2)

- currency - RUB / USD / EUR
  
- description - описание

- meta - B, произвольные метаданные

- status - pending / succeeded / failed

- idempotency_key - уникальный ключ

- webhook_url - URL клиента

- created_at - дата создания

- processed_at - дата обработки

## Таблица outbox

- id - UUID

- event_type - тип события (payment.created)

- payload - B с данными

- status - pending / published

- retry_count - счетчик

- created_at / published_at - даты

## Конфигурация

Все настройки через переменные окружения (файл .env):

- API_KEY - статический ключ для X-API-Key

- POSTGRES_* - подключение к PostgreSQL

- RABBITMQ_* - подключение к RabbitMQ

- PAYMENTS_QUEUE - имя основной очереди (по умолчанию payments.new)

- PAYMENTS_DLQ - имя DLQ (по умолчанию payments.new.dlq)

- WEBHOOK_TIMEOUT - таймаут webhook в секундах

- WEBHOOK_MAX_RETRIES - количество попыток доставки

## Структура проекта

```
async-payment-service/
├── app/
│   ├── api/v1/  # HTTP-эндпоинты
│   ├── consumers/  # Consumer платежей
│   ├── core/  # Конфиг, безопасность
│   ├── db/  # Подключение к БД
│   ├── models/  # SQLAlchemy-модели
│   ├── publishers/  # Outbox publisher
│   ├── schemas/  # Pydantic-схемы
│   └── main.py  # Точка входа FastAPI
├── alembic/  # Миграции
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

## Проверка работоспособности

Создать платеж и убедиться, что:

- API вернул 202 Accepted и payment_id;

- в таблице payments появилась запись со статусом pending;

- в таблице outbox появилась запись со статусом pending;

- через пару секунд воркер outbox_publisher перевел ее в published;

- consumer обновил статус платежа до succeeded или failed;

- на webhook пришел  с результатом.

Проверить таблицы:

```
docker compose exec postgres psql -U payment -d payment_db -c "SELECT id, status FROM payments;"
docker compose exec postgres psql -U payment -d payment_db -c "SELECT id, event_type, status FROM outbox;"
```

Проверить очереди RabbitMQ:

```
docker compose exec rabbitmq rabbitmqctl list_queues name messages
```
