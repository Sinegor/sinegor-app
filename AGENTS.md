
# Project Instructions

## Authoritative Documentation

The following documents define the approved project requirements:

- `docs/Анализатор-217. Меморандум.md` — business purpose, services, and organizational requirements.
- `docs/Анализатор-217.md` — MVP functionality, workflows, order lifecycle, and document handling.
- `docs/Анализатор-архитектура.md` — approved architecture, infrastructure, and integration boundaries.
- `docs/План разработки SINEGOR — MVP.md` — implementation stages and sequence.

Verify actual file paths before use.

Read the relevant documents before implementing or modifying functionality.
Consult the development plan before starting a new implementation stage.

Do not independently change approved product or architectural decisions.
Do not implement features explicitly excluded from the MVP.
Distinguish approved requirements from proposals and unresolved questions.
Report contradictions or missing requirements instead of inventing solutions.
Do not modify project documentation unless explicitly requested.

## Task Reports

For subsequent user tasks, create completion reports in `docs/reports/`.
This is standing authorization to create these reports without a separate request or confirmation.
This authorization does not extend to changes to other project documentation.

Уточнение владельца от 17.11.2026: документы о выполнении заданий ИИ-агентом
(отчёты и сопровождающие материалы проверок без секретов) передавать на локальный
хост Fedora в `/home/sinegor/documents/IT/Pet_project/sinegor-app/docs/reports/`,
как и ранее. В итоговом ответе давать ссылки на фактически переданные локальные файлы.
Копии на VPS могут сохраняться, но не заменяют передачу владельцу на локальный хост.
Это разрешённое исключение из правила работы только на VPS для отчётных документов:
исходный код, рабочие конфигурации и служебные скрипты продолжают изменяться на VPS.
Секреты, ключи и приватные эксплуатационные архивы в комплект отчётов не включать.

## Project File Storage

Постоянные правила хранения владельца от 17.11.2026:

- Файлы, подлежащие версионированию, включая исходный код, конфигурации, постоянные скрипты и техническую документацию, размещать в Git-репозитории `/home/sinegoradmin/apps/sinegor-app` на VPS.
- В `/home/sinegoradmin/apps/sinegor-app-private` размещать только файлы, которые не должны попадать в Git и необходимы для приватной конфигурации приложения.
- Временные, тестовые, диагностические и архивные материалы размещать в соответствующих каталогах `/home/sinegoradmin/apps/sinegor-app-artifacts`, а не в private. Исторические материалы последующих этапов хранить в `archive/`, по каталогам этапов, например `archive/III-7/`.
- Действующие системные файлы и состояния служб сохранять в предназначенных для них системных каталогах.

Правило передачи отчётов на локальный хост из раздела Task Reports сохраняется.
Правила хранения сами по себе не разрешают удалять или перемещать существующие файлы вне порученного объёма.

## Architecture & Business Boundaries

- Keep business logic in the modular FastAPI backend.
- Use Strapi exclusively for public website content.
- Maintain React Router Framework Mode with SSR for public pages.
- Transfer client documents and deliver results directly through Yandex Disk, not through the website.
- Limit Yandex Disk API integration to approved administrative operations.
- Manage access permissions for shared Yandex Disk folders manually.
- Store signed agreements separately from deletable order materials.
- Treat order completion and document deletion as separate processes.
- Require explicit administrator confirmation for document deletion.
- Do not introduce infrastructure components or automation without demonstrated need and approval.
- Prefer minimal changes consistent with approved architecture.

## Security

- Keep secrets in untracked environment files.
- Never log authentication links, cookies, document contents, or SQL values.
- Enforce authorization in the backend.
- Do not perform destructive operations without appropriate authorization.

## Development Guidance

- Follow existing project conventions and configuration.
- Inspect relevant code and configuration before modifying them.
- Use existing tools and dependencies where possible.
- Run relevant checks after code changes and report their results.
- Do not claim verification unless checks were actually performed.

## Additional Instructions

- For backend implementation, follow `apps/api/AGENTS.md`.
- For backend setup, migrations, development commands, and testing procedures, consult `docs/development/backend-operations.md`.
- For repository structure, commit conventions, and pull requests, consult `docs/development/repository-workflow.md`.

Do not load unrelated documentation solely because it is listed here.

## SINEGOR LAB — правила работы ИИ-агента с исходным кодом и Git

Постоянные правила владельца от 17.11.2026.

1. Единственная рабочая среда разработки — VPS. Все дальнейшие изменения исходного кода, конфигураций и служебных скриптов выполнять непосредственно в репозитории `/home/sinegoradmin/apps/sinegor-app` на VPS.
2. Локальная копия проекта на Fedora не является источником актуального кода. Агент должен игнорировать её отставание от серверной версии, не требовать синхронизации и не предлагать замену серверного кода локальным. За основу работы принимать фактическое состояние репозитория на VPS.
3. Git — зона ответственности владельца проекта. Агент не выполняет самостоятельно `commit`, `push`, `pull`, `fetch`, `merge`, `rebase`, `reset`, `checkout` и другие операции Git, изменяющие состояние репозитория или его историю, если владелец прямо не поручил соответствующую операцию.
4. Не запрашивать согласования по обычным вопросам Git. Агент самостоятельно выполняет порученные изменения файлов, не ожидая создания коммита или доставки изменений владельцем. Не требовать commit ID для продолжения работы, если это не обусловлено реальной технической необходимостью.
5. Сообщать владельцу о проблемах Git только при наличии критической опасности: риска потери кода или данных, необратимого изменения истории, перезаписи актуальной серверной версии либо невозможности безопасно продолжить порученную работу. Обычные расхождения ревизий, незакоммиченные изменения и отставание локальной копии сами по себе не являются основанием для уведомления.

Эти правила имеют приоритет над ранее сформированными рекомендациями по организации Git-процесса.

Ограничение: запрет на самостоятельные операции Git не распространяется на чтение состояния репозитория (`git status`, `git diff`, `git log` и аналогичные команды), необходимое для выполнения задания.
