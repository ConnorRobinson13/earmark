# Contributing

Thanks for taking a look. This started as a personal tool to replace
EveryDollar with something that matches how I actually think about money, so
it's opinionated by design — but issues and PRs are welcome.

## Ground rules

- **Open an issue first** for anything non-trivial, so we can agree on the
  approach before you spend time on it.
- **Never commit personal data or secrets.** No `.env`, no database dumps, no
  CSV exports, no real transactions. The `.gitignore` already blocks the usual
  culprits (`.env`, `backups/`, `history_csvs/`, `seed.py`) — don't work around
  it.
- Keep the fund-based model intact (see the README's "How this thinks about
  money" section). Features that quietly break the envelope/rollover semantics
  will be pushed back on.

## Dev setup

```bash
cp .env.example .env        # fill in what you need; all keys are optional
docker compose up -d
docker compose exec backend alembic upgrade head
```

- Backend: FastAPI, auto-reloads on save (code is bind-mounted).
- Frontend: Vite dev server, hot-reloads.
- DB migrations: Alembic. Add one with
  `docker compose exec backend alembic revision -m "what changed"` and edit the
  generated file under `backend/alembic/versions/`.

## Style

- Match the surrounding code. The backend leans on type hints and small,
  well-commented service functions; the comments explain *why*, not *what*.
- Money is always `Decimal` on the backend, never `float`.
- Keep balance/accounting logic in `backend/app/services/` so the API routers
  and the MCP server share one source of truth.

## Pull requests

- Keep them focused — one concern per PR.
- Describe the behavior change and how you verified it.
- If it touches the data model, include the migration.
