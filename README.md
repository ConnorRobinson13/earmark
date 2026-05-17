# Budget App

Self-hosted fund-based budgeting PWA. Replaces EveryDollar.

## Stack
- **Backend:** FastAPI + SQLAlchemy + Alembic
- **Frontend:** React + Vite (PWA)
- **DB:** Postgres 16 + pgvector
- **Embeddings:** Ollama (`mxbai-embed-large`) running on host
- **LLM:** Anthropic API for categorization
- **Bank import:** Plaid (sandbox → production)

## Quick start

```bash
cp .env.example .env  # fill in keys
docker compose up -d
docker compose exec backend alembic upgrade head
# pull embedding model on host
ollama pull mxbai-embed-large
```

- API: http://localhost:8080
- Frontend: http://localhost:5173
- Postgres: localhost:5433 (user `budget`, db `budget`)

## Layout
```
backend/   FastAPI app + Alembic
frontend/  Vite + React PWA
```

## Core model
Every category is a **fund** — a persistent balance that rolls over month to month. Goals are funds with `kind='goal'`. Credit cards are pass-through; the swipe is an expense from a fund.

See repo spec for full design.
