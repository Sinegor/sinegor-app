# API-контракт

`api.json` содержит экспорт OpenAPI настоящего FastAPI. Источник истины — его схемы и маршруты. Web использует генерируемые типы `apps/web/app/lib/api/schema.d.ts` и клиент `openapi-fetch`.

После изменения HTTP-контракта из корня:

```bash
apps/api/.venv/bin/python scripts/export_openapi.py
cd apps/web
npm run api:generate
npm run typecheck
```

Экспорт не читает dotenv и не подключается к БД. Обе команды генерации перезаписывают соответствующие файлы; сгенерированные типы не редактируются вручную. Окружение Python должно быть установлено по `apps/api/uv.lock`, npm-зависимости — по `apps/web/package-lock.json`. Тестирование — в [README E2E](../../tests/e2e/README.md).
