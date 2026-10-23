
# FastAPI Backend Instructions

Follow the root `AGENTS.md` and approved project architecture.

## Module Organization

- `src/sinegor/modules/` — business domains.
- `src/sinegor/integrations/` — external integrations.
- `src/sinegor/db/` — persistence.
- `src/sinegor/jobs/` — CLI jobs.
- `migrations/versions/` — Alembic revisions.
- `tests/` — backend tests.

Preserve the modular architecture and existing module boundaries.

## Python Conventions

- Use Python 3.12 and uv.
- Follow `.editorconfig`: UTF-8, LF, four-space indentation for Python.
- Follow Ruff configuration for formatting, imports, and the 100-character line limit.
- Use `snake_case` for functions and modules.
- Use `PascalCase` for classes.
- Use `UPPER_SNAKE_CASE` for constants.

## Database Changes

- Register new ORM models in `sinegor.db.models`.
- Add Alembic revisions for schema changes.
- Inspect generated migrations before applying them.
- Follow the migration safety requirements in `docs/development/backend-operations.md`.

## Testing

- Use pytest.
- Name test files `test_*.py` and test functions `test_*`.
- Place database integration tests in `tests/integration/`.
- Mark integration tests with `integration`.
- Add regression tests for bug fixes.
- Do not assume a numeric coverage threshold.

## Commands & Procedures

Before running development, migration, or test commands,
consult `docs/development/backend-operations.md`.

Select commands appropriate to the task.
Do not run setup or migration commands merely to perform code review.
