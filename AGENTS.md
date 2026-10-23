# Project Documentation & Requirements
The following documents are authoritative sources for project requirements:
  -docs/Анализатор-217. Меморандум.md — business purpose, services, and organizational requirements.
  -docs/Анализатор-217.md — MVP functionality, workflows, order lifecycle, and document handling.
  -docs/Анализатор-архитектура.md — approved technical architecture, infrastructure, and integration boundaries.
  - docs/План разработки SINEGOR — MVP.md 

Verify the actual file paths before relying on them.

Before implementing or modifying functionality, consult the relevant documentation.
  -Do not independently change approved product or architectural decisions.
  -Do not implement features explicitly excluded from the MVP.
  -Distinguish approved requirements from proposals and unresolved questions.
  -Report contradictions or missing requirements instead of silently inventing solutions.
  -Do not modify project documentation unless explicitly requested.

# Implementation Boundaries
Keep business logic in the modular FastAPI backend.
Use Strapi exclusively for public website content.
Maintain React Router Framework Mode with SSR for public pages.
Client document transfer and result delivery take place directly through Yandex Disk, not through the website.
Yandex Disk API integration must remain within the approved administrative operations.
Access permissions for shared Yandex Disk folders are managed manually.
Signed agreements must be stored separately from deletable order materials.
Order completion and document deletion are separate processes.
Document deletion requires explicit administrator confirmation.
Do not introduce additional infrastructure components or automation without a demonstrated need and approval.
Prefer minimal changes consistent with existing architecture and conventions.

# Repository Guidelines

## Project Structure & Module Organization

- `apps/api/src/sinegor/` contains the FastAPI backend: `modules/` for business domains, `integrations/` for external services, `db/` for persistence, and `jobs/` for CLI tasks.
- `apps/api/migrations/versions/` holds Alembic revisions; backend tests live in `apps/api/tests/`.
- `apps/web/` and `apps/cms/` are scaffolds for React/TypeScript and Strapi. Static assets belong in their `public/` directories. Frontend package scripts are not initialized yet.
- `contracts/openapi/` reserves API contracts; `tests/e2e/` reserves browser tests.
- `docs/` contains requirements, architecture, and implementation status; `infra/compose/` contains local infrastructure.

## Build, Test, and Development Commands

Use Python 3.12 and uv. Run these commands from `apps/api/`:

```bash
cp .env.development.example .env
uv sync --locked
docker compose -f ../../infra/compose/backend.dev.yaml up -d --wait
uv run --locked alembic upgrade head
uv run --locked uvicorn sinegor.main:create_app --factory --reload --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
uv run --locked pytest -m "not integration"
uv run --locked ruff check .
uv run --locked ruff format --check .
```

These install dependencies, start PostgreSQL, migrate the database, launch the API, and run local checks. See `apps/api/README.md` for Compose v1 alternatives. From the repository root, run `python3 scripts/check_structure.py` to validate the scaffold.

## Coding Style & Naming Conventions

Follow `.editorconfig`: UTF-8, LF, two-space indentation generally and four spaces for Python. Ruff enforces formatting, import ordering, and a 100-character Python line limit. Use `snake_case` functions/modules, `PascalCase` classes, and `UPPER_SNAKE_CASE` constants.

Register new ORM models in `sinegor.db.models`. Add new Alembic revisions for schema changes and inspect generated migrations.

## Testing Guidelines

Use pytest with `test_*.py` files and `test_*` functions. Place database tests in `tests/integration/` and mark them `integration`. Add regression tests for bug fixes; no numeric coverage threshold is configured.

Run the full suite with `TEST_DATABASE_URL` set and `uv run --locked pytest`. Use a dedicated empty PostgreSQL database ending in `_test`: migration tests perform destructive downgrades. Without this variable, integration tests skip.

## Commit & Pull Request Guidelines

Git history is unavailable in this checkout. Use concise imperative messages, optionally scoped: `auth: preserve links after SMTP failure`.

PRs should explain the behavior change, link relevant issues, report validation commands/results, and identify migrations or configuration changes. Include screenshots for UI changes.

## Security & Configuration

Keep secrets in untracked environment files. Never log authentication links, cookies, document contents, or SQL values. Enforce authorization in the backend; Strapi owns public content only.
