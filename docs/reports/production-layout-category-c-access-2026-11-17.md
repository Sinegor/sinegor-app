# Доступ для переноса категории C

Дата: 17.11.2026, Europe/Moscow. Поручение владельца разрешает перенос C; повторного согласования обычного переноса не требуется.

Сценарий [production-layout-category-c-move-2026-11-17.py](production-layout-category-c-move-2026-11-17.py) использует готовый перечень 80 объектов: 54 файла, 26 каталогов. Новый аудит не выполняется.

Точные операции переименования относительно `sinegor-app-private` → `sinegor-app-artifacts/archive`:

- `iii5-reboot-baseline-2026-11-15.json` → `III-5/iii5-reboot-baseline-2026-11-15.json`.
- `iii6-ip-r-74cc255b61332b32cbcd72002fd5eae6/connection.json` → `III-6/` с тем же вложенным путём.
- `iii6-ip-r-8a078cd57a33bf8635398c30d6c249d6/{connection,result}.json` → `III-6/` с теми же вложенными путями (две отдельные операции).
- `iii6-c3-28a33d70c17d4101018bb67fb1648f86/browser-result.json` → `III-6/` с тем же вложенным путём.
- `https/cms-client-ca.pem` → `III-6/https/cms-client-ca.pem`.
- `iii7` целиком → `III-7`.

Используется renameat2(RENAME_NOREPLACE) на том же разделе. Замена существующего назначения и копирование между разделами запрещены. При ошибке проверки выполняются обратные переименования без создания копий. Новые архивные каталоги — 0700, sinegoradmin; метаданные переносимых объектов сохраняются, включая root-owned rollback. Файлы C вне private, A/B/D, исторический код и действующие production-конфигурации не изменяются.

До переноса проверяется полнота только переносимого комплекта и отсутствие его использования указанными действующими launcher/selectors/units. При обнаружении активной зависимости сценарий прекращает работу до перемещения. Не выполняются Docker/systemctl, jobs, миграции, HTTP проверки, restart/reload/reboot, выпуск сертификатов или восстановление production. Пароли/env содержимым в вывод и отчёты не попадают.

Один root-запуск нужен, потому что `/home/sinegoradmin/apps` не разрешает создание каталога пользователю, а rollback III-7 закрыт root:root/0700. Сценарий проверяется по SHA256 до исполнения. Сначала проверяется SSH-соединение, затем открывается FIFO. Пароль идёт напрямую из FIFO в sudo stdin без чтения моделью, сохранения или вывода.

Выполните на локальной Fedora, оставив терминал открытым до передачи:

```bash
sinegor_c_access_dir=$(mktemp -d /tmp/sinegor-sudo.XXXXXX)
chmod 700 "$sinegor_c_access_dir"
mkfifo -m 600 "$sinegor_c_access_dir/password.fifo"
printf 'Передайте агенту только путь: %s/password.fifo\n' "$sinegor_c_access_dir"
IFS= read -r -s -p 'Пароль sudo VPS для переноса C: ' sinegor_c_password
printf '\n'
printf '%s\n' "$sinegor_c_password" > "$sinegor_c_access_dir/password.fifo"
unset sinegor_c_password
```

В чат передайте только напечатанный `/tmp/sinegor-sudo.…/password.fifo`. Пароль не передавайте. Ожидание терминала на printf до подключения агента нормально.

Результат и безопасное evidence после переноса передаются в локальный `docs/reports/`. Созданные ранее исторические отчёты не переписываются. Второй запуск инвентаризации и работа с D не выполняются.
