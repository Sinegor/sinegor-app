# SINEGOR LAB — завершение реорганизации production-хранилища

Дата: 17.11.2026, Europe/Moscow.

Удалены пять проверенных исходных экземпляров из private:

- /home/sinegoradmin/apps/sinegor-app-private/https/production.https.yaml
- /home/sinegoradmin/apps/sinegor-app-private/https/production.bootstrap.yaml
- /home/sinegoradmin/apps/sinegor-app-private/https/nginx/nginx.https.conf
- /home/sinegoradmin/apps/sinegor-app-private/https/nginx/nginx.bootstrap.conf
- /home/sinegoradmin/apps/sinegor-app-private/https/deploy-tls.py

Исходные экземпляры сохранены вне private и проверены по SHA256. Материалы C уже перенесены; их старые пути отсутствуют. Остальные private файлы не удалялись. Оставлена одна ссылка совместимости на production.https.yaml в репозитории для существующих Docker labels; прежний пустой nginx-каталог удалён, если в нём не появилось других файлов.

После отдельного согласования пересоздан только proxy с конфигурацией infra/proxy, selector III-7 переведён на репозиторный override. Другие четыре контейнера, все образы, volumes и настройки безопасности сохранены.

Комплексная приёмка пройдена: основной и bootstrap Compose; nginx -t; trusted HTTPS FastAPI/SSR/Strapi/Content API; mTLS admin 403 без сертификата и 200 с сертификатом; native admin 401 без входа; Certbot timer/renewal dependencies/действующий сертификат; host launcher check III-7 через новый selector; отсутствие открытых внутренних портов и нарушенных ссылок. Certbot renew и выпуск сертификатов не выполнялись. Подробное безопасное evidence — production-layout-final-evidence-2026-11-17.json.

В серверном AGENTS.md закреплены четыре правила хранения: versioned source/config/scripts/technical docs — в репозитории; только необходимая приватная конфигурация — в private; временные/test/diagnostic/archive материалы — в artifacts; действующие системные файлы/state — в системных каталогах. Исключение о локальной передаче отчётов сохранено. infra/README.md отражает фактические рабочие пути.

Повторной инвентаризации, удаления прочих A/C/D, изменений архитектуры, бизнес-логики, migrations, Git commit/push, restart Docker или reboot не было. Препятствий по выполненному объёму не осталось.

Все шесть job timers и watchdog подтверждены enabled/active при заключительной проверке путей.
