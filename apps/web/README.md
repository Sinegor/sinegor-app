# Web — SINEGOR LAB

React / TypeScript и React Router Framework Mode с SSR. Реализованы публичный сайт, вход, кабинет заказчика и административный интерфейс. Опубликованный контент Strapi читается сервером без пересборки. Авторизацию и бизнес-правила проверяет FastAPI.

## Запуск

Node.js 22.12+ (для общего контура с CMS — до 27), npm. Из `apps/web`:

```bash
npm ci
test -f .env || cp .env.example .env
npm run dev
```

Адрес — `http://localhost:3000`. Vite перенаправляет `/api` в `API_ORIGIN` (по умолчанию `http://127.0.0.1:8000`), сохраняя Origin. Backend `PUBLIC_ORIGIN` должен совпадать с адресом браузера. Запуск backend — в [README API](../api/README.md).

`CMS_ORIGIN` — серверный адрес Strapi, например `http://127.0.0.1:1337`. `CMS_MEDIA_ORIGIN` — доступный браузеру адрес медиа; по умолчанию используется `CMS_ORIGIN`. Без `CMS_ORIGIN` предусмотрены встроенные публичные страницы для автономной разработки, список публикаций пуст. При настроенной, но недоступной CMS SSR возвращает 503; неопубликованная/несуществующая страница — 404. Подготовка и публикация контента — в [README CMS](../cms/README.md).

## Сборка и проверки

```bash
npm run typecheck
npm test
npm run format:check
npm run build
HOST=127.0.0.1 PORT=3000 npm start
```

`npm start` запускает собранный SSR через `react-router-serve`. Proxy из `vite.config.ts` работает только в dev. Для собранного приложения требуется внешний reverse proxy: `/api/*` → FastAPI, остальные маршруты → SSR. Сам `npm start` запросы в FastAPI не перенаправляет. Переменные CMS передавайте процессу SSR; для собранного сервера не полагайтесь на загрузку `.env` через Vite. Готовая production-конфигурация proxy/TLS относится к T2.

`npm run test:e2e` запускает браузерные проверки интерфейса с перехватом внутренних API, поднимая собственный SSR на `localhost:3102`; Chromium устанавливается через `npx playwright install chromium`. Для этого набора оставьте `CMS_ORIGIN` не заданным. Он дополняет [живой интеграционный E2E-контур](../../tests/e2e/README.md), который сам запускает FastAPI, PostgreSQL и Strapi без подмены их API.

## Код

- `app/routes/public/` — услуги, контакты, публикации, консультация.
- `app/routes/auth/` — запрос и обработка Magic Link, отдельный вход администратора.
- `app/routes/customer/` — заказы клиента, PDF, ссылка на Диск, отметка передачи, разрешение удаления.
- `app/routes/admin/` — заказчики, заказы, соглашения, оплата, подтверждение удаления.
- `app/layouts/` — отдельные публичный, клиентский и административный макеты.
- `app/components/` — общие компоненты интерфейса.
- `app/lib/api/` — HTTP-клиент FastAPI и типы, генерируемые из OpenAPI.
- `app/lib/cms.server.ts`, `app/lib/cms.ts` — серверное чтение CMS и типы контента.
- `app/styles/`, `public/` — стили и публичные статические ресурсы.

Генерация API-типов: `npm run api:generate` после [экспорта контракта](../../contracts/openapi/README.md). Персональные данные не кэшировать публично. Проверки интерфейса не заменяют авторизацию FastAPI. PDF соглашений не размещать в `public/`.
