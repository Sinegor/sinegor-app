# SINEGOR API

Этапы B1–B3: запускаемый FastAPI backend с PostgreSQL, SQLAlchemy 2, Alembic, настройками окружения, JSON-логами и pytest. Добавлены 11 доменных сущностей, авторизация, приглашения, серверные сессии и проверки доступа; управление заказами реализуется на следующих этапах. Модель и ограничения описаны в `../../docs/data-model.md`.

## Требования

Python 3.12+ (проект закреплён на 3.12), uv, Docker с Compose v2 для локальной PostgreSQL. Зависимости и хеши зафиксированы в `uv.lock`.

## Локальный запуск

Команды выполняются из `apps/api`:

```bash
cp .env.development.example .env
uv sync --locked
docker compose -f ../../infra/compose/backend.dev.yaml up -d --wait
uv run --locked alembic upgrade head
uv run --locked uvicorn sinegor.main:create_app --factory --reload --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

PostgreSQL публикуется только на `127.0.0.1:5432`. Если порт занят, задайте `POSTGRES_PORT` при запуске Compose и измените порт в `DATABASE_URL`. Пароль в dev-шаблоне используется только в локальном окружении. В текущей среде установлен Docker Compose v1 (`docker-compose`). Для него используйте ту же конфигурацию, заменив `docker compose` на `docker-compose`, а `up -d --wait` на `up -d`; перед миграциями дождитесь успешного `docker-compose -f ../../infra/compose/backend.dev.yaml exec postgres pg_isready -U sinegor -d sinegor`.

Остановка БД: `docker compose -f ../../infra/compose/backend.dev.yaml down` (том сохраняется).

- `GET /api/health/live` — процесс работает, без обращения к БД.
- `GET /api/health/ready` — `SELECT 1` через SQLAlchemy; при недоступной БД возвращает 503.
- `/docs`, `/redoc`, `/openapi.json` — доступны в разработке, отключены в production.

Фабрика создаёт engine и session factory на lifespan, закрывает pool при остановке. Приложение может запуститься при недоступной БД; до её восстановления readiness возвращает 503. Таблицы автоматически при старте не создаются: используйте Alembic.

## Конфигурация

По умолчанию читается `apps/api/.env` независимо от текущего каталога. `SINEGOR_ENV_FILE` выбирает другой dotenv-файл; переменные процесса имеют приоритет. Неизвестные поля общего dotenv игнорируются.

| Переменная | Назначение |
|---|---|
| `APP_ENV` | `development`, `test`, `production` |
| `DATABASE_URL` | Обязательный URL `postgresql+psycopg://user:password@host:port/database` |
| `PUBLIC_ORIGIN` | Origin frontend, в production обязателен HTTPS |
| `LOG_LEVEL` | DEBUG/INFO/WARNING/ERROR/CRITICAL; DEBUG в production запрещён |
| `DB_CONNECT_TIMEOUT` | Таймаут соединения, 1–30 секунд; по умолчанию 5 |

Пароли со специальными символами нужно URL-кодировать. Дополнительные query-параметры DATABASE_URL пока не поддерживаются. Настройки подключения расширяются отдельными проверяемыми параметрами по необходимости.

Production-шаблон: `.env.production.example`. Укажите реальные реквизиты БД и домен, затем:

```bash
uv sync --locked --no-dev
SINEGOR_ENV_FILE=/secure/path/backend.env uv run --locked --no-dev alembic upgrade head
SINEGOR_ENV_FILE=/secure/path/backend.env uv run --locked --no-dev uvicorn sinegor.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

Это команда приложения за reverse proxy; полный production Compose, TLS и резервирование относятся к этапу T2. Не используйте `--reload` в эксплуатации. Клиентские сессии и административная авторизация реализованы в B3; настройка ключей, SMTP и первого администратора описана в `../../docs/authentication.md`. Для production за proxy настройте доверие forwarded-заголовкам только от адреса этого proxy вместо --no-proxy-headers.

## Миграции

```bash
uv run --locked alembic current
uv run --locked alembic upgrade head
uv run --locked alembic check
uv run --locked alembic revision --autogenerate -m "describe change"
```

`0001_backend_baseline` фиксирует начальную точку; `0002_domain_models` создаёт все 11 доменных таблиц B2; `0003_auth_security` добавляет состояние защиты входа B3. Подключение и metadata едины с приложением. Все модели импортируются через `sinegor.db.models` в `migrations/env.py`; при добавлении модели обновляйте реестр; сгенерированный diff нужно проверить. Откат на тестовой БД: `uv run --locked alembic downgrade base`.

## Тесты

```bash
uv run --locked pytest -m "not integration"
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Для интеграционных проверок создайте отдельную пустую БД:

```bash
docker compose -f ../../infra/compose/backend.dev.yaml exec postgres createdb -U sinegor sinegor_test
TEST_DATABASE_URL=postgresql+psycopg://sinegor:sinegor_dev@127.0.0.1:5432/sinegor_test uv run --locked pytest
```

Интеграционные тесты пропускаются без TEST_DATABASE_URL. Имя тестовой БД должно оканчиваться на `_test`; миграционный тест требует БД без данных и посторонних таблиц. Он проверяет B1 → B2, повторный upgrade, проверку расхождений metadata, downgrade и восстановление head. Тесты моделей выполняются в откатываемых транзакциях. Не подключайте этот набор к БД приложения.

Тесты не читают рабочий dotenv. Проверяются настройки development/production, обработка 404/422/500/503, отсутствие секретов в ответах и логах, корреляция request ID, закрытие/rollback сессий, реальное подключение и миграции PostgreSQL.

## Логи и ошибки

JSON-логи в stdout: событие, уровень, UTC timestamp, request ID, HTTP-метод, статус и длительность. URL, query, тело, cookie, SQL-параметры и текст неожиданных исключений не выводятся. Ошибки имеют `error.code`, `error.message`, `request_id`; каждый ответ получает `X-Request-ID`. Стандартный access log Uvicorn отключайте через `--no-access-log`, чтобы не записывать ссылки авторизации.

## Код

- `api/` — маршруты, единый формат ошибок.
- `core/` — настройки и логирование.
- `db/` — metadata, engine, request session. Коммит выполняет бизнес-сервис явно; ошибка вызывает rollback, завершение запроса закрывает сессию.
- `modules/` — auth, customers, orders, agreements, disk, notifications, retention, audit.
- `integrations/` — будущие серверные адаптеры SMTP, Telegram, Яндекс Диска, закрытых PDF.
- `jobs/` — будущие CLI фоновых задач.

Подключённые справочники: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), [SQLAlchemy pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html), [Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html), [uv projects](https://docs.astral.sh/uv/guides/projects/).

## Авторизация B3

См. [настройку и HTTP-контракт](../../docs/authentication.md). В production обязательны SESSION_SECRET и AUTH_ENCRYPTION_KEY. Для первого администратора: `uv run --locked python -m sinegor.jobs.create_admin --email admin@example.ru`. Перед POST требуется получить `/api/auth/csrf` и передать X-CSRF-Token / Origin.
