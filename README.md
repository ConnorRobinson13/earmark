# Ledger — fund-based budgeting

[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![Postgres](https://img.shields.io/badge/Postgres-16_+_pgvector-4169E1?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![PWA](https://img.shields.io/badge/PWA-installable-5A0FC8?logo=pwa&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-talk_to_your_money-C15F3C)

A self-hosted budgeting app built around **funds** (envelopes) instead of
monthly line items. It's a personal replacement for EveryDollar/YNAB that keeps
the parts of zero-based budgeting that work, drops the monthly-reset busywork,
and layers on bank sync and an AI assistant you can literally talk to about
your money.

Runs entirely on your own machine with Docker.

![Quickstart](docs/quickstart.gif)

> **Heads up:** this is a single-user app with **no login**. Run it locally.
> See [SECURITY.md](SECURITY.md) before you expose it anywhere.

---

## How this thinks about money

The whole app is one idea: **every dollar you keep gets a job, and jobs
persist.** If you've used EveryDollar or YNAB, this will feel familiar — with
one deliberate difference (funds roll over; they don't reset each month).

### 1. Funds are persistent envelopes
A **fund** is a named pot of money with a balance that **rolls over month to
month**. "Groceries," "Car insurance," "Vacation" are all funds. Unlike
EveryDollar — where every category resets to zero on the 1st — a fund's leftover
(or overspend) carries forward. If you underspend groceries in March, that money
is still in the groceries fund in April. This is the single biggest departure
from the tool it replaces, and the reason the accounting is built around
running balances rather than monthly buckets.

Funds come in two kinds:
- **Operational** — ordinary spending categories (rent, food, gas).
- **Goal** — money you're accumulating or paying down. Three flavors:
  - **savings** — hit a target balance (e.g. $5,000 emergency fund).
  - **contribution** — hit a total contributed in a period (Roth IRA, HSA, 401k).
  - **debt** — a balance you pay *down* toward zero; supports a real lender
    `min_payment` so the app shows your actual bill, not a principal estimate.

### 2. You budget against *planned* income, not deposits
Each month has a **planned income** figure — what you expect to bring in. You
then **assign** that money into funds. The headline number, **Unassigned**, is:

```
Unassigned = (cumulative planned income) − (cumulative money assigned to funds)
```

Assigning against the *plan* (not against actual paychecks) means a deposit
landing mid-month doesn't jerk your numbers around — it was already accounted
for. Zero-based budgeting works when Unassigned reaches $0: every planned dollar
has a fund.

### 3. Accounts hold money; funds earmark it
**Accounts** are where money physically lives — checking, savings, credit cards,
investments, and a carved-out emergency fund. **Funds** are how you've *labeled*
your spendable cash. They're independent on purpose:

- **Spendable cash** = live checking + savings balances. Your emergency-fund and
  investment accounts are excluded — that money isn't for spending.
- **Net worth** = every account netted together (assets minus credit/debt),
  captured as snapshots over time so you can watch the trend.
- **Credit cards are pass-through.** A swipe is recorded as an *expense from a
  fund*, the moment it happens — not as new debt to reconcile later. The card
  balance is tracked separately as money owed; paying it off moves cash, it
  doesn't touch your budget.

### 4. Transactions flow in, you approve them
Bank transactions (via Plaid) land in an **inbox**. For each one the app
suggests a fund — using vector similarity against how you categorized similar
merchants before, plus an optional LLM pass. You approve (or fix) it, and it
becomes a real transaction against that fund. Only *posted* transactions are
ingested; pending ones are skipped until they settle, so nothing gets
double-counted when the amount changes.

You can also skip Plaid entirely and add transactions by hand.

---

## Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI + SQLAlchemy + Alembic |
| Frontend | React + Vite (installable PWA) |
| Database | Postgres 16 + [pgvector](https://github.com/pgvector/pgvector) |
| Embeddings | [Ollama](https://ollama.com) (`mxbai-embed-large`) on the host |
| Categorization | Anthropic API (optional) |
| Bank sync | Plaid (optional; sandbox → production) |
| AI assistant | MCP server wrapping the API ("talk to your money") |

Everything except Ollama runs in Docker. Ollama runs on the host so the
container can reach your GPU/CPU without wrestling with passthrough.

---

## Spin it up

### Prerequisites
- **Docker** + Docker Compose.
- **[Ollama](https://ollama.com)** running on the host (only needed for the
  smart fund suggestions). Optional — the app runs without it, you just don't
  get similarity-based suggestions.
- API keys are **all optional**. With none of them you get a fully functional
  manual budgeting app; add them to unlock sync and AI.

### 1. Configure
```bash
cp .env.example .env
```
Fill in whatever you want (all optional):
- `ANTHROPIC_API_KEY` — LLM-assisted categorization.
- `PLAID_CLIENT_ID` / `PLAID_SECRET` / `PLAID_ENV` — bank sync. Start with
  `PLAID_ENV=sandbox`.
- `MCP_AUTH_TOKEN` — bearer token for the MCP server (`openssl rand -hex 32`).

### 2. Pull the embedding model (optional)
```bash
ollama pull mxbai-embed-large
```

### 3. Bring up the stack
```bash
docker compose up -d
docker compose exec backend alembic upgrade head   # run DB migrations
```

That's it. Services:

| Service | URL | Notes |
|---|---|---|
| Frontend | http://localhost:5174 | the app (installable PWA) |
| API | http://localhost:8080 | FastAPI + `/docs` for the OpenAPI UI |
| Postgres | localhost:5433 | user `budget`, db `budget` |
| MCP server | http://localhost:9000/mcp | AI assistant endpoint |

### 4. First run
Open the frontend, set your planned income for the month, create a few funds,
and assign your income until **Unassigned** hits $0. If you wired up Plaid, use
**Settings → connect a bank** to link an institution; new transactions show up
in the **Inbox** for you to approve.

---

## Optional: bank sync with Plaid

Linking a bank exchanges a Plaid public token for an access token (stored in the
`plaid_items` table) and pulls accounts + transactions. A background job syncs
daily at 6am; you can also trigger `POST /plaid/sync` anytime. Notes:

- Only **posted** transactions are ingested (pending ones are skipped until they
  settle — this avoids duplicates when a pending amount is replaced on posting).
- `PLAID_SYNC_FLOOR_DATE` (in `config.py`) drops transactions older than a cutoff
  so a first sync doesn't backfill years of history you've already accounted for.
- **Investment** accounts are balance-tracked only — their buys/sells/dividends
  are intentionally *not* dropped into your spending inbox.

## Optional: talk to your money (MCP)

The MCP server wraps the API so an AI client can read your finances and (with
confirmation) make changes — assign to funds, record transactions, mark goal
contributions, project retirement, and more. It's gated by `MCP_AUTH_TOKEN`.
See [mcp/README.md](mcp/README.md) for connecting Claude Code, claude.ai, or
litellm.

---

## Layout
```
backend/    FastAPI app, services (accounting lives in services/), Alembic migrations
frontend/   Vite + React PWA
mcp/        MCP server that wraps the backend API
docker-compose.yml
```

All balance and accounting math lives in `backend/app/services/` so the API and
the MCP server share exactly one source of truth.

---

## Security

Single-user, **no authentication**, meant for localhost. Do not expose it to the
internet without putting your own auth in front. Read [SECURITY.md](SECURITY.md).

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © 2026 Connor Robinson
