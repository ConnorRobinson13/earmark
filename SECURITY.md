# Security

This is a **single-user, self-hosted** application. It is designed to run on
your own machine (or a private network you control) and has **no built-in user
authentication** on the web app or API. Anyone who can reach the ports it
serves can read and modify your financial data.

## Do not expose this to the public internet

The FastAPI backend (`:8080`) and the frontend (`:5174`) ship with **no auth**.
Do not port-forward them, put them on a public IP, or tunnel them without
placing your own authentication in front (a reverse proxy with auth, a VPN,
Tailscale, Cloudflare Access, etc.).

The MCP server (`:9000`) is gated by a bearer token (`MCP_AUTH_TOKEN`). If you
tunnel it (e.g. to use it from claude.ai), **set a strong token first**
(`openssl rand -hex 32`). If the token is empty the MCP server runs open — that
is only safe on localhost.

## Secrets

- All secrets live in `.env`, which is gitignored. Never commit it.
- `.env.example` documents the variables with empty values — keep it that way.
- Your Plaid **access tokens** are stored in the Postgres database (in the
  `plaid_items` table). Treat the database volume as sensitive: it is the key
  to your linked bank accounts. Back it up somewhere encrypted, not in the repo.

## Handling your own data

- The Docker `postgres_data` volume holds all of your transactions, balances,
  and Plaid tokens. It is never committed, but be mindful of where it lives.
- Files under `backups/`, `backend/scripts/history_csvs/`, and
  `backend/scripts/seed.py` are gitignored precisely because they tend to hold
  real personal financial data. Keep them out of version control.

## Reporting a vulnerability

This is a personal hobby project with no security guarantees. If you find a
serious issue, please open a GitHub issue (omit any sensitive details) or reach
out to the maintainer directly.
