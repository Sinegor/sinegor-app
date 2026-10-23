# SINEGOR API

Этапы B1–B8: FastAPI backend с PostgreSQL, SQLAlchemy 2, Alembic, настройками окружения, JSON-логами и pytest. Реализованы авторизация, карточки заказчиков, заказы, ручная оплата, журнал, обмен PDF, ограниченная интеграция Яндекс Диска, сохраняемая очередь email/Telegram и полуавтоматическое удаление материалов. Модель и ограничения — в `../../docs/data-model.md`; эксплуатационные контракты — в `../../docs/authentication.md`, `orders.md`, `agreements.md`, `disk.md`, `notifications.md`, `retention.md`.

## Требования

Python 3.12+ (проект закреплён на 3.12), uv, Docker с Compose v2 для локальной PostgreSQL. Зависимости и хеши зафиксированы в `uv.lock`.

## Локальный запуск

Команды выполняются из `apps/api`:

```bash
test -f .env || cp .env.development.example .env
uv sync --locked
docker compose -f ../../infra/compose/backend.dev.yaml up -d --wait
uv run --locked alembic upgrade head
uv run --locked uvicorn sinegor.main:create_app --factory --reload --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

Копирование нужно только при отсутствии `.env`: не перезаписывайте уже заполненные настройки интеграций и ключи. Перед запуском проверьте `DATABASE_URL` в существующем файле. Локальная рабочая база Compose — `sinegor`; строка для неё приведена в `.env.development.example`. Приложение не читает шаблоны `.example` автоматически и не получает рабочий URL из `TEST_DATABASE_URL`. Если PostgreSQL уже запущен другим Compose-проектом, используйте этот экземпляр, не запускайте второй на занятом порту.

PostgreSQL публикуется только на `127.0.0.1:5432`. Если порт занят, задайте `POSTGRES_PORT` при запуске Compose и измените порт в `DATABASE_URL`. Пароль в dev-шаблоне используется только в локальном окружении. Если доступен только Docker Compose v1 (`docker-compose`), используйте ту же конфигурацию, заменив `docker compose` на `docker-compose`, а `up -d --wait` на `up -d`; перед миграциями дождитесь успешного `docker-compose -f ../../infra/compose/backend.dev.yaml exec postgres pg_isready -U sinegor -d sinegor`.

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
| `DATABASE_URL` | Обязательный URL рабочей БД `postgresql+psycopg://user:password@host:port/database`; локально база `sinegor` |
| `PUBLIC_ORIGIN` | Origin frontend, в production обязателен HTTPS |
| `LOG_LEVEL` | DEBUG/INFO/WARNING/ERROR/CRITICAL; DEBUG в production запрещён |
| `DB_CONNECT_TIMEOUT` | Таймаут соединения, 1–30 секунд; по умолчанию 5 |

Пароли со специальными символами нужно URL-кодировать. Дополнительные query-параметры DATABASE_URL пока не поддерживаются. Настройки подключения расширяются отдельными проверяемыми параметрами по необходимости.

Параметры SMTP и Telegram описаны в [B7](../../docs/notifications.md), токен и корень Диска — в [B6](../../docs/disk.md). Меняйте отправителя и реквизиты почты через окружение, без изменения кода.

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

Текущий head — `0009_notifications`: 15 таблиц приложения и `alembic_version`. `0002_domain_models` создаёт 11 доменных таблиц, `0003_auth_security` — состояние авторизации, `0005_customer_events` — журнал карточек, `0006_agreements` — версии/очистку PDF, `0007_disk_operations` и `0008_disk_deletion_intent` — состояние операций Диска, `0009_notifications` — очередь уведомлений. B8 использует существующую модель запросов удаления без новой миграции.

Для проверки уже выполненного обновления достаточно `alembic current` и `alembic check`: current должен совпадать с head, а check — не находить новых операций. Эти проверки не применяют миграции. Подключение и metadata едины с приложением; модели регистрируются через `sinegor.db.models`. Откаты `alembic downgrade base` допускаются только на выделенной тестовой БД, не на рабочей `sinegor`.

## Тесты

```bash
uv run --locked pytest -m "not integration"
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Для полного набора интеграционных проверок создайте отдельную роль с собственным паролем и пустую БД. В примере `createuser` запросит пароль интерактивно; замените `TEST_PASSWORD` в URL на выбранный пароль с URL-кодированием специальных символов:

```bash
docker compose -f ../../infra/compose/backend.dev.yaml exec postgres createuser -U sinegor --pwprompt sinegor_test
docker compose -f ../../infra/compose/backend.dev.yaml exec postgres createdb -U sinegor -O sinegor_test sinegor_test
TEST_DATABASE_URL='postgresql+psycopg://sinegor_test:TEST_PASSWORD@127.0.0.1:5432/sinegor_test' uv run --locked pytest
```

Интеграционные тесты пропускаются без TEST_DATABASE_URL. Имя тестовой БД должно оканчиваться на `_test`; миграционный тест требует БД без данных и посторонних таблиц. Он проверяет B1 → B2, повторный upgrade, проверку расхождений metadata, downgrade и восстановление head. Тесты моделей выполняются в откатываемых транзакциях. Не подключайте этот набор к БД приложения.

Полный набор включает production-проверку cookies, которая запрещает пароль `sinegor_dev`. Поэтому тестовая роль использует отдельный пароль; рабочие реквизиты и DATABASE_URL в `.env` для запуска тестов не заменяются.

Тесты не читают рабочий dotenv. Проверяются настройки development/production, обработка 404/422/500/503, отсутствие секретов в ответах и логах, корреляция request ID, закрытие/rollback сессий, реальное подключение и миграции PostgreSQL.

Живой совместный прогон FastAPI, PostgreSQL, Strapi и SSR запускается из корня командой `apps/api/.venv/bin/python tests/e2e/run.py`. Он сам создаёт и удаляет тестовые БД и не использует рабочие `.env`; внешние каналы локальные. Подготовка и границы — в [README E2E](../../tests/e2e/README.md). Эксплуатационные команды собраны в [backend-operations](../../docs/development/backend-operations.md).

## Логи и ошибки

JSON-логи в stdout: событие, уровень, UTC timestamp, request ID, HTTP-метод, статус и длительность. URL, query, тело, cookie, SQL-параметры и текст неожиданных исключений не выводятся. Ошибки имеют `error.code`, `error.message`, `request_id`; каждый ответ получает `X-Request-ID`. Стандартный access log Uvicorn отключайте через `--no-access-log`, чтобы не записывать ссылки авторизации.

## Код

- `api/` — маршруты, единый формат ошибок.
- `core/` — настройки и логирование.
- `db/` — metadata, engine, request session. Коммит выполняет бизнес-сервис явно; ошибка вызывает rollback, завершение запроса закрывает сессию.
- `modules/` — auth, customers, orders, agreements, disk, notifications, retention, audit.
- `integrations/` — серверные адаптеры SMTP, Telegram и Яндекс Диска; закрытые PDF обслуживает `modules/agreements/storage.py`.
- `jobs/` — отдельные CLI создания администратора, обработки заказов/уведомлений и очистки.

Подключённые справочники: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), [SQLAlchemy pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html), [Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html), [uv projects](https://docs.astral.sh/uv/guides/projects/).

## Авторизация B3

См. [настройку и HTTP-контракт](../../docs/authentication.md). В production обязательны SESSION_SECRET и AUTH_ENCRYPTION_KEY. Для первого администратора: `uv run --locked python -m sinegor.jobs.create_admin --email admin@example.ru`. Перед POST требуется получить `/api/auth/csrf` и передать X-CSRF-Token / Origin.

## Заказчики и заказы B4

API, допустимые переходы, ручная оплата, отметки передачи и журнал описаны в [контракте заказов](../../docs/orders.md). Примените миграции до head. `process_orders` переводит ранее утверждённые заказы в ожидание материалов, завершает готовые спустя 14 дней и создаёт запросы удаления B8. Готовность фиксируется после SMTP-уведомления B7; ошибка отправки оставляет задание для повтора.

## Соглашения B5

Версии и очистка PDF добавлены миграцией `0006_agreements`; применяйте все миграции до head через `uv run --locked alembic upgrade head`. Новая зависимость pypdf зафиксирована в uv.lock; обновление окружения — `uv sync --locked`. Закрытые PDF по умолчанию хранятся в `apps/api/storage/agreements`, настройка VPS — `AGREEMENT_STORAGE_DIR=/var/lib/sinegor/agreements`. Каталог должен иметь права 0700 и принадлежать пользователю приложения. Максимальный размер PDF задаётся AGREEMENT_MAX_BYTES (по умолчанию 20 МиБ).

Загрузка принимает raw application/pdf и X-Agreement-Revision; утверждение выполняется по версии просмотренного файла. При утверждении заказ сразу переходит в awaiting_materials. Периодическая очистка временных файлов: `uv run --locked python -m sinegor.jobs.cleanup_agreements`. Контракт, ошибки, восстановление и образец curl — в [документации B5](../../docs/agreements.md).

## Диск, уведомления и удаление B6–B8

- [B6: настройки, привязка папок, асинхронное удаление и восстановление после потери ответа](../../docs/disk.md).
- [B7: SMTP/Telegram, ответы API и повторная доставка](../../docs/notifications.md).
- [B8: досрочное разрешение, подтверждение, отсрочка и независимое завершение](../../docs/retention.md).

Команды запускаются из `apps/api`, с одним рабочим dotenv и тем же закрытым хранилищем, что API:

| Команда после `uv run --locked python -m` | Назначение / расписание |
|---|---|
| `sinegor.jobs.process_orders` | Переходы заказов, запросы удаления, истечение отсрочек; `orders.cron.example` |
| `sinegor.jobs.process_notifications` | Напоминания и доставка очереди; `notifications.cron.example` |
| `sinegor.jobs.cleanup_agreements` | Удаление устаревших и потерянных временных PDF; `agreements.cron.example` |
| `sinegor.jobs.purge_auth` | Очистка истёкших токенов, сессий и счётчиков; можно запускать ежедневно |
| `sinegor.jobs.create_admin --email admin@example.ru` | Однократное интерактивное создание администратора с TOTP |

Образцы находятся в `infra/scheduler/`; замените абсолютный путь и при необходимости задайте `SINEGOR_ENV_FILE`. Они не устанавливаются автоматически. `process_orders` не удаляет материалы: после решения администратора используется HTTP-маршрут папки. Окончательные PDF и журнал заказов сохраняются. Перед ручным запуском `process_notifications` на рабочей БД учитывайте, что команда отправит доступные задания реальным получателям.

Если `uv` недоступен, но `.venv` уже установлен по lock-файлу, используйте `.venv/bin/python -m pytest`, `.venv/bin/python -m alembic ...`, `.venv/bin/python -m sinegor.jobs...` и `.venv/bin/ruff`. Это не заменяет установку зависимостей через `uv sync --locked` при развёртывании.
