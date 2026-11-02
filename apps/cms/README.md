# CMS

Strapi 5 Community Edition обслуживает только публичные страницы, услуги, публикации, SEO и медиа. Модели, draft/publish и read-only API реализованы. Заказчики, заказы и соглашения хранятся в FastAPI, в другой БД.

- `src/api/` — content types и контроллер публичного чтения.
- `src/components/` — повторно используемые компоненты контента.
- `config/` — сервер, отдельная БД, настройки медиа и доступа.
- `public/` — публичные ресурсы CMS; uploads в отдельном томе.

## PostgreSQL

Для новой локальной PostgreSQL можно из корня запустить совместно два Compose-файла:

```bash
docker compose -f infra/compose/backend.dev.yaml -f infra/compose/cms.dev.yaml up -d --wait
```

`cms.dev.yaml` добавляет начальный скрипт создания роли и БД `sinegor_cms`; пароль берётся из `CMS_DATABASE_PASSWORD` (локальный default `sinegor_cms_dev`). Он должен совпадать с `DATABASE_PASSWORD` CMS. PostgreSQL init-скрипты выполняются только при создании пустого тома.

Если проектная PostgreSQL уже работает, используйте её точное имя контейнера, задайте `CMS_DATABASE_PASSWORD` в локальной оболочке и выполните из корня:

```bash
sh scripts/init-cms-db.sh ИМЯ_КОНТЕЙНЕРА_POSTGRES
```

Скрипт создаёт отсутствующие роль/БД и не меняет пароль существующей роли. Для существующего тома не используйте `down -v` ради повторной инициализации. Особенности Compose v1 и занятого порта — в [README API](../api/README.md).

## Запуск и контент

Нужны Node.js 22.12–26 для совместимости с web и npm. Из `apps/cms`:

```bash
npm ci
test -f .env || cp .env.example .env
```

В `.env` укажите отдельные реквизиты CMS, фактический порт PostgreSQL, случайные `APP_KEYS`, `ADMIN_JWT_SECRET`, `API_TOKEN_SALT`, `TRANSFER_TOKEN_SALT`, `ENCRYPTION_KEY`, `JWT_SECRET`. Сохраните файл вне Git. Затем:

```bash
npm run develop
```

По умолчанию сервер слушает `127.0.0.1:1337`, Admin — `/admin`, health — `/_health` (204). Создание редактора выполняется через первый вход в Admin. `CMS_PUBLIC_ORIGIN` задаёт адрес CMS; `HOST` и `PORT` — адрес прослушивания.

`npm run seed` явно и идемпотентно импортирует отсутствующие страницы/услуги из `scripts/f4-content.json` **как черновики**. Команда меняет выбранную CMS-БД и сама ничего не публикует. Проверьте данные и опубликуйте документы в Admin. Публичная регистрация отключена при bootstrap.

Публичные маршруты `/api/public-content/pages`, `/api/public-content/services`, `/api/public-content/publications` и варианты `/{slug}` возвращают только опубликованные документы; параметры клиента не включают draft-режим. Публичная запись не предусмотрена. `public/uploads/` содержит публичные медиа (предел загрузки 100 МиБ); PDF соглашений сюда не помещаются. Настройка SSR — в [README web](../web/README.md).

На главной странице web поля `video`, `image` и `videoCaption` страницы `home` задают видео, заставку проигрывателя и подпись. При отсутствии этих значений frontend использует встроенные `apps/web/assets/Презентация_1.1.mp4`, `apps/web/assets/заставка.jpg` и подпись «Видеопрезентация SINEGOR LAB.». Встроенные файлы поставляются со сборкой web; загружать их в Strapi для показа на главной не требуется. Подробнее — [видеопрезентация на главной](../web/README.md#видеопрезентация-на-главной).

## Сборка и тест

```bash
npm run build
npm start
npm run test:integration
```

Последняя команда запускает [изолированный контур](../../tests/e2e/README.md) с `--suite cms`, используя Python из `apps/api/.venv`, Docker и Playwright web. Проверяется настоящая Strapi, публикация, медиа и SSR. Рабочий `.env` и существующая БД не используются. Тестовые документы создаются и публикуются только в одноразовой БД.

В эксплуатации CMS Admin должен быть доступен через защищённый административный канал; публично нужны только read-only контент и медиа. Compose для Strapi/web, TLS/proxy, отдельный постоянный том uploads и проверенное резервирование ещё относятся к T2. Имеющийся `cms.dev.yaml` запускает PostgreSQL, а не сам Strapi.
