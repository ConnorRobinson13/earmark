# Earmark MCP Server — "talk to your money"

A Streamable-HTTP MCP server that wraps the budget-app API. It never touches
Postgres directly — every tool calls the FastAPI backend so the EveryDollar-style
balance math and write-safety logic stay in one place.

The tools forward; they don't decide. Amounts keep the sign they were given,
months go over the wire in whichever form the caller used, and a rejection comes
back in the backend's own words. Anything re-derived here is a second answer to a
question the backend has already answered, and the wrong one wins quietly.

## Running

Comes up with the rest of the stack:

```bash
docker compose up -d        # starts postgres, backend, frontend, mcp
```

The MCP server listens on `http://localhost:9000/mcp`.

## Auth

A bearer token gates the server. It lives in `budget-app/.env` as
`MCP_AUTH_TOKEN`. Every client must send `Authorization: Bearer <token>`.
If `MCP_AUTH_TOKEN` is empty the server runs open (local-only — don't tunnel it).

## Tools

**Read:** `financial_overview`, `list_funds`, `list_goals`,
`search_transactions`, `net_worth`, `list_accounts`, `goals_to_move`,
`project_retirement`

**Write** (mutate the ledger — confirm with the user first):
`assign_to_fund`, `record_transaction`, `mark_goal_contributed`,
`set_planned_income`

Each tool's docstring is its whole interface as far as the model is concerned, so
a docstring that disagrees with the endpoint is a bug, not a typo.

## Tests

Nothing needs to be running — the suite swaps a fake backend into `server._http`
and asserts on the requests the tools build:

```bash
cd mcp
pip install -r requirements-dev.txt
pytest
```

## Connecting

### Claude Code
`.mcp.json` in the repo root already points at it. Claude Code picks it up
automatically when you open the project.

### claude.ai (custom connector)
claude.ai can't reach `localhost` — expose it with a tunnel:

```bash
cloudflared tunnel --url http://localhost:9000
```

Take the `https://<random>.trycloudflare.com` URL it prints, then in claude.ai:
Settings → Connectors → Add custom connector → URL `https://<random>.trycloudflare.com/mcp`,
and add the `Authorization: Bearer <token>` header.

Charts/visuals: the tools return structured data (e.g. `project_retirement`
returns a year-by-year series); claude.ai renders the charts as artifacts.

### litellm
Point litellm's MCP config at `http://localhost:9000/mcp` with the bearer header.
