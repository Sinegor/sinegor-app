# Миграции Alembic

`env.py` использует Settings, подключение SQLAlchemy и Base.metadata приложения. DATABASE_URL берётся из окружения / выбранного dotenv, а не alembic.ini.

Начальная ревизия `0001_backend_baseline` не создаёт доменных таблиц. Ревизия `0002_domain_models` создаёт 11 таблиц B2. Все модели зарегистрированы через `sinegor.db.models`, импортируемый в env.py. При добавлении модели обновляйте реестр, создавайте и проверяйте автогенерируемую ревизию.

Из `apps/api`:

```bash
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
uv run --locked alembic revision --autogenerate -m "describe change"
```

Откаты тестируются на выделенной БД. Таблицами CMS управляет Strapi независимо от этих миграций.

B3: `0003_auth_security` добавляет auth_rate_limits и admin_users.last_totp_step, включая CHECK неотрицательности шага. Миграционный тест проверяет обновление существующей записи администратора B2 без потери данных.
