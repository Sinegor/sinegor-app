
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

## Git Operations

Git staging and commits are managed exclusively by the user.

- Read-only Git operations are allowed, including
  `git status`, `git diff`, `git log`, and `git show`.
- Do not stage or unstage files (`git add`, `git restore --staged`,
  `git reset`).
- Do not create, amend, or delete commits.
- Do not perform Git operations that modify the index,
  commit history, branches, or repository metadata.
- Do not bypass these restrictions through scripts,
  Skills, subagents, plugins, or MCP tools.

Modify project files and run relevant checks as needed.
Leave staging, committing, and repository management to the user.

