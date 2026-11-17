# III-7: пути материалов восстановления

Целевой архив после переноса категории C: `/home/sinegoradmin/apps/sinegor-app-artifacts/archive/III-7/`.

- Snapshot: `rollback-iii7-20261116-1-144931/` — прежние `files/`, `compose.env`, `manifest.json`.
- Release bundle и evidence: `deploy-20261116/`.
- Завершённое испытание restart/reboot: `restart-acceptance-20261116/`.
- Отдельная историческая проверка: `root-preflight.py`.

Исторические файлы сохранены побайтно, включая закреплённые контрольные суммы. В них остаются прежние ссылки:

| Файл внутри III-7 | Прежняя ссылка | Как использовать после переноса |
|---|---|---|
| `deploy-20261116/manifest.json` | `resume_from.backup` → private/iii7/rollback-iii7-20261116-1-144931 | Читать snapshot из нового `archive/III-7/rollback-iii7-20261116-1-144931` |
| `deploy-20261116/deployment-evidence.json` | `backup` с тем же абсолютным путём | Историческое evidence; snapshot теперь по новому пути |
| `deploy-20261116/deploy.py` | Вычисляемый `PRIVATE / 'iii7'` | Исторический установщик; не запускать для восстановления |
| `restart-acceptance-20261116/deploy.py` | Вычисляемый старый `DEPLOY` | Завершённый тест; не адаптировать и не запускать |
| `restart-acceptance-20261116/acceptance.service` | Старые абсолютные ExecStart/Pending | Исторический unit; не устанавливать и не включать |

Правило разрешения архивной ссылки при чтении manifest/evidence:

```python
from pathlib import Path
old_archive = Path('/home/sinegoradmin/apps/sinegor-app-private/iii7')
new_archive = Path('/home/sinegoradmin/apps/sinegor-app-artifacts/archive/III-7')
def current_archive_path(recorded_path: str) -> Path:
    return new_archive / Path(recorded_path).relative_to(old_archive)
```

Меняется только префикс местонахождения архивного материала. Рабочие пути репозитория, `/etc/sinegor/jobs.env`, private env, main/HTTPS Compose и установленные units не перенаправляются. Исторические manifests и тесты не переписываются; прежняя проверка SHA256 rollback manifest остаётся применимой.

Восстановление production — отдельная операция после согласования владельца. Перед ним нужны stop/gate/drain, проверка отсутствия новых пользовательских правок и выбор нужного snapshot. Читать исходные файлы из нового `rollback…/files` и `compose.env`; действия по изменению приложения/units/selector выполнять только в пределах отдельного согласования. Автоматически восстанавливать БД или повторно запускать исторический установщик/тест reboot не следует.

При текущем переносе проверяются только полнота, неизменность материалов и новые recovery paths. Перенос сам по себе не выполняет откат и не меняет работающий production.
