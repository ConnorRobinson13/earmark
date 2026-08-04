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
- The daily 06:00 Plaid sync is opt-in via `ENABLE_SCHEDULER=1`, which compose
  sets for you. Running the backend outside compose leaves it off — set it
  yourself if you want the cron job.
- Frontend: Vite dev server, hot-reloads.
- DB migrations: Alembic. Add one with
  `docker compose exec backend alembic revision -m "what changed"` and edit the
  generated file under `backend/alembic/versions/`.

## Tests

The backend test suite stands up its own throwaway pgvector database, so it
doesn't need — and won't touch — the compose stack. It needs Docker running and
nothing else:

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

If you'd rather point it at a database you already have, set
`TEST_DATABASE_URL`. The suite **drops every table in it**, rebuilds the schema
by running the migrations, and **truncates every table between tests**, so give
it a database of its own — never the one behind `docker compose` on port 5433.

The MCP server has its own suite, and that one needs nothing at all — no Docker,
no database, no backend. It stands a fake API in front of the tools and checks
the requests they build:

```bash
cd mcp
pip install -r requirements-dev.txt
pytest
```

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
