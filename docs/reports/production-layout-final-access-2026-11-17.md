# Завершение реорганизации production-хранилища: согласуемые действия

Дата: 17.11.2026, Europe/Moscow. Повторная инвентаризация не выполняется. Основание — подтверждённые переносы B/C и поручение завершить очистку и приёмку.

Работающий production пока не переключён. Сценарий [production-layout-final-apply-2026-11-17.py](production-layout-final-apply-2026-11-17.py) подготовлен для указанного блока.

## Требующее согласования переключение

1. Повторно проверить пять original/saved SHA256, пять новых repo-файлов и системный hook. Сравнить Compose до/после: единственное семантическое изменение — source bind Nginx на `infra/proxy`. Проверить отсутствие старых C paths и наличие перенесённых материалов.
2. Атомарно заменить только SINEGOR_COMPOSE_OVERRIDE в `/etc/sinegor/jobs.env` с private HTTPS YAML на `/home/sinegoradmin/apps/sinegor-app/infra/compose/production.https.yaml`, сохранив root:root/0600, activation gate и остальные значения.
3. Из корня репозитория пересоздать только proxy:

```bash
docker compose -p sinegor-lab-prod \
  --env-file /home/sinegoradmin/apps/sinegor-app-private/compose.env \
  -f infra/compose/production.yaml \
  -f infra/compose/production.https.yaml \
  up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 proxy
```

Сайт может быть кратко недоступен. API/CMS/web/PostgreSQL не пересоздаются; образы, постоянные volumes, mTLS и прочие настройки безопасности сохраняются. Docker и VPS не перезапускаются.

## Итоговая проверка и разрешённая очистка

После переключения один комплекс проверок: пять healthy; main/bootstrap Compose и относительные bind/build пути; nginx -t; trusted HTTPS API/SSR/Strapi/Content API; mTLS 403 без сертификата, 200 с существующим сертификатом Fedora, native Strapi 401 без входа; Certbot timer/config/deploy hook/валидность сертификата; read-only launcher check III-7 через новый selector; закрытые внутренние порты; неизменные четыре контейнера/images/volumes; разрешение Docker config_files labels.

Ключ mTLS остаётся на Fedora. Root-сценарий ждёт только безопасные статусы локальной проверки в новом файле artifacts/diagnostics. При отказе проверки он восстанавливает пять исходников и исходный selector в том же sudo-сеансе, затем возвращает только proxy к прежнему override.

Только после успешных проверок убрать эти пять regular originals из private:

- `https/production.https.yaml`;
- `https/production.bootstrap.yaml`;
- `https/nginx/nginx.https.conf`;
- `https/nginx/nginx.bootstrap.conf`;
- `https/deploy-tls.py`.

На месте первого файла оставить **одну ссылку совместимости** на репозиторный production.https.yaml: старый путь записан в исторических Docker labels действующих API/CMS/web/DB. Это устраняет нарушенные ссылки без пересоздания этих контейнеров и без второй копии YAML. Пустой старый nginx-каталог удалить только через rmdir; неизвестные файлы не удалять.

Сохранённые оригиналы B вне private, архив C, системный Certbot hook, рабочие env, TLS/Certbot, данные, swap и остальные A/C/D не удаляются. Дополнительных архивных копий не создаётся. Исторические тесты не адаптируются. Commit/push/pull и другие операции изменения Git не выполняются.

После успеха обновить фактические рабочие пути в infra/README.md. В AGENTS.md четыре постоянных правила хранения фиксируются до переключения; исключение о локальной передаче отчётов сохраняется.

## Одноразовый sudo-доступ

Нужен для selector, Docker и итоговых read-only проверок. Это доступ для конкретного сценария; согласование переключения должно быть получено отдельно. Пароль передаётся FIFO → SSH stdin → sudo без сохранения, вывода или чтения моделью. SSH и SHA256 сценария проверяются до открытия FIFO.

```bash
sinegor_final_access_dir=$(mktemp -d /tmp/sinegor-sudo.XXXXXX)
chmod 700 "$sinegor_final_access_dir"
mkfifo -m 600 "$sinegor_final_access_dir/password.fifo"
printf 'Передайте агенту только путь: %s/password.fifo\n' "$sinegor_final_access_dir"
IFS= read -r -s -p 'Пароль sudo VPS для завершения реорганизации: ' sinegor_final_password
printf '\n'
printf '%s\n' "$sinegor_final_password" > "$sinegor_final_access_dir/password.fifo"
unset sinegor_final_password
```

Передайте только путь `/tmp/sinegor-sudo.…/password.fifo`, оставив терминал открытым. Сам пароль в чат не передавайте.
