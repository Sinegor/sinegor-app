# Инфраструктура

## Production: конфигурация в репозитории

Production работает на VPS в `/home/sinegoradmin/apps/sinegor-app`, Compose project — `sinegor-lab-prod`.

- `compose/production.yaml` — основной набор сервисов, сетей и постоянных томов.
- `compose/production.https.yaml` — HTTPS override с конфигурацией Nginx из `infra/proxy`.
- `compose/production.bootstrap.yaml` — override первоначального HTTP/ACME bootstrap.
- `proxy/nginx.https.conf` и `proxy/nginx.bootstrap.conf` — соответствующие конфигурации Nginx.
- `proxy/nginx.conf` — существующая базовая конфигурация; сохраняется.
- `../scripts/deployment/deploy-tls.py` — исходник действующего Certbot deploy hook.

Секреты и рабочие env остаются в `/home/sinegoradmin/apps/sinegor-app-private`, TLS/CA/ACME — в `/var/lib/sinegor-lab-prod`, Certbot accounts/renewal/live/archive — в `/etc/letsencrypt`. Эти данные не включаются в Git. Постоянные Docker volumes не перемещаются.

Штатная команда из корня серверного репозитория:

```bash
docker compose \
  -p sinegor-lab-prod \
  --env-file /home/sinegoradmin/apps/sinegor-app-private/compose.env \
  -f infra/compose/production.yaml \
  -f infra/compose/production.https.yaml \
  <операция>
```

Относительные пути Compose считаются от каталога первого файла — `infra/compose`: build `../../apps/...`, Nginx bind `../proxy`. Не добавлять `--project-directory` с корнем репозитория: это меняет разрешение относительных путей.

## Рабочие пути после реорганизации 17.11.2026

Production использует infra/compose/production.https.yaml и read-only bind infra/proxy. В /etc/sinegor/jobs.env выбран этот же override. Пять прежних исходных файлов private/https удалены после проверки сохранённых экземпляров и приёмки production.

Для исторических Docker labels API/CMS/web/DB оставлена одна совместимая ссылка private/https/production.https.yaml на YAML в репозитории. Это ссылка, а не дополнительная копия конфигурации. Пересоздан только proxy; образы и остальные четыре контейнера сохранены.

Исходные экземпляры B сохранены в /home/sinegoradmin/sinegor-app-deployment-originals/category-b-20261117. Архив C находится в /home/sinegoradmin/apps/sinegor-app-artifacts/archive/ по этапам. Системный /usr/local/sbin/sinegor-lab-prod-deploy-tls и Certbot/TLS state не изменялись.

Откат является отдельно согласуемой операцией: восстановить четыре прежних Compose/Nginx файла из сохранённых оригиналов, вернуть прежний selector /etc/sinegor/jobs.env и пересоздать только proxy со старым override. Ссылку заменять атомарно, не записывать через неё в Git-файл. БД, volumes, Git и приложение автоматически не откатывать.

## Development и прочие инструменты

- `compose/backend.dev.yaml` — dev PostgreSQL; `compose/cms.dev.yaml` добавляет подготовку CMS-БД.
- `postgres/init-cms.sh` и `../scripts/init-cms-db.sh` — подготовка CMS; существующие БД при переносе не изменяются.
- `scheduler/` — launcher и примеры systemd timers/CLI; наличие файлов не разрешает включать дополнительные расписания.
- `../tests/e2e` — изолированный тестовый контур. При переносе категории B он не запускается.

Существующие ограничения архитектуры, подтверждения удаления материалов и защиты итоговых соглашений сохраняются.

## Исторические материалы этапов

Целевое хранилище C — `/home/sinegoradmin/apps/sinegor-app-artifacts/archive/`, по каталогам `III-5/`, `III-6/`, `III-7/`. Материалы C, уже находящиеся вне private, этим переносом не затрагиваются. Актуальные пути III-7 и порядок разрешения старых архивных ссылок — в [инструкции восстановления scheduler](scheduler/RECOVERY.md). Сам перенос не переключает работающий production.
