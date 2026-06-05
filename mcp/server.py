"""Budget App MCP server — "talk to your money".

Wraps the budget-app FastAPI (never the DB directly) so all the EveryDollar-style
balance math, paired-transaction safety, and goal/settlement logic stay in one
place. Exposes a curated set of conversational tools over Streamable HTTP.

Env:
  BUDGET_API_URL   base URL of the backend API   (default http://backend:8000)
  MCP_AUTH_TOKEN   bearer token clients must send (default "" = no auth, local only)
  MCP_HOST/MCP_PORT  bind address                 (default 0.0.0.0:9000)
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API = os.environ.get("BUDGET_API_URL", "http://backend:8000").rstrip("/")
AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")

mcp = FastMCP(
    "Budget",
    host=os.environ.get("MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_PORT", "9000")),
)


def _get(path: str, params: dict | None = None) -> Any:
    r = httpx.get(f"{API}{path}", params=params or {}, timeout=30.0)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict) -> Any:
    r = httpx.post(f"{API}{path}", json=body, timeout=30.0)
    r.raise_for_status()
    return r.json() if r.content else {}


def _put(path: str, body: dict) -> Any:
    r = httpx.put(f"{API}{path}", json=body, timeout=30.0)
    r.raise_for_status()
    return r.json() if r.content else {}


def _this_month() -> str:
    t = date.today()
    return f"{t.year}-{t.month:02d}-01"


# ─────────────────────────── READ TOOLS ───────────────────────────

@mcp.tool()
def financial_overview(month: str = "") -> dict:
    """Snapshot of the budget for a month: unassigned money, planned vs actual
    income, net cash, spent, saved, and every fund with its balance.

    month: YYYY-MM-01 (or YYYY-MM). Empty = current month.
    """
    return _get("/dashboard", {"month": month} if month else None)


@mcp.tool()
def list_funds(month: str = "") -> list:
    """All operational spending funds with this-month assigned/spent/balance.
    month: YYYY-MM-01. Empty = current month."""
    data = _get("/dashboard", {"month": month} if month else None)
    return [f for f in data["funds"] if f["kind"] == "operational"]


@mcp.tool()
def list_goals() -> list:
    """All goals with progress. Savings goals track a balance; contribution
    goals (Roth/HSA/401k) track contribution_ytd against an annual target."""
    funds = _get("/funds")
    return [f for f in funds if f["kind"] == "goal"]


@mcp.tool()
def search_transactions(
    start: str = "",
    end: str = "",
    merchant: str = "",
    fund_id: int = 0,
    type: str = "",
    min_amount: float = 0,
    max_amount: float = 0,
) -> dict:
    """Search transactions for analytical questions ("how much on coffee since
    March"). Returns matching rows + summary (net, total_outflow, total_inflow).

    start/end: YYYY-MM-DD inclusive. merchant: case-insensitive substring.
    type: expense | income | assignment | transfer. 0/empty = no filter.
    Amounts: signed — negative is money out, positive is money in.
    """
    params: dict = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    if merchant:
        params["merchant"] = merchant
    if fund_id:
        params["fund_id"] = fund_id
    if type:
        params["type"] = type
    if min_amount:
        params["min_amount"] = min_amount
    if max_amount:
        params["max_amount"] = max_amount
    return _get("/transactions/search", params)


@mcp.tool()
def net_worth() -> dict:
    """Current net worth: total plus breakdown by liquid / emergency fund /
    investments / credit-card debt, and a per-account list."""
    return _get("/networth")


@mcp.tool()
def list_accounts() -> list:
    """All accounts with type, balance, and last-synced time."""
    return _get("/accounts")


@mcp.tool()
def goals_to_move(month: str = "") -> list:
    """Goals with money assigned this month but not yet physically moved to
    their backing account. month: YYYY-MM-01. Empty = current month."""
    return _get("/settlements/pending", {"month": month} if month else None)


@mcp.tool()
def project_retirement(
    current_age: int,
    retire_age: int,
    annual_return_pct: float = 8.0,
    monthly_contribution: float = 0.0,
) -> dict:
    """Project investment net worth at retirement. Compounds the CURRENT
    investment-account total plus monthly contributions at the given annual
    return. Returns the final value and a year-by-year series for charting.
    """
    nw = _get("/networth")
    start = float(nw["investment"])
    years = max(0, retire_age - current_age)
    r = annual_return_pct / 100.0
    series = [{"age": current_age, "year": 0, "value": round(start, 2)}]
    bal = start
    for y in range(1, years + 1):
        bal = bal * (1 + r) + monthly_contribution * 12
        series.append({"age": current_age + y, "year": y, "value": round(bal, 2)})
    total_contrib = monthly_contribution * 12 * years
    return {
        "starting_investment": round(start, 2),
        "years": years,
        "annual_return_pct": annual_return_pct,
        "monthly_contribution": monthly_contribution,
        "total_contributed": round(total_contrib, 2),
        "compounded_growth": round(bal - start - total_contrib, 2),
        "final_value": round(bal, 2),
        "series": series,
    }


# ─────────────────────────── WRITE TOOLS ───────────────────────────
# These mutate the ledger. Confirm the amount + target with the user in plain
# language BEFORE calling — there is no undo from the chat side.

@mcp.tool()
def assign_to_fund(fund_id: int, amount: float, month: str = "") -> dict:
    """Assign money from Unassigned to a fund (budgeting move). CONFIRM the
    fund and amount with the user before calling — this changes the budget.

    amount: positive to add to the fund, negative to pull back to Unassigned.
    month: YYYY-MM-01. Empty = current month (assignment dates to today).
    """
    m = month or _this_month()
    today = date.today().isoformat()
    is_current = m == _this_month()
    return _post("/transactions/assign", {
        "fund_id": fund_id,
        "amount": amount,
        "date": today if is_current else m,
        "notes": "Assigned via MCP",
    })


@mcp.tool()
def record_transaction(
    fund_id: int,
    amount: float,
    type: str = "expense",
    merchant: str = "",
    txn_date: str = "",
) -> dict:
    """Record a transaction directly against a fund. CONFIRM details with the
    user before calling.

    type: 'expense' (money out) or 'income' (money in, e.g. a reimbursement).
    amount: positive number; direction is set by `type`.
    txn_date: YYYY-MM-DD. Empty = today.
    """
    return _post("/transactions/quick-add", {
        "fund_id": fund_id,
        "amount": abs(amount),
        "type": type,
        "merchant": merchant,
        "date": txn_date or date.today().isoformat(),
    })


@mcp.tool()
def mark_goal_contributed(
    goal_id: int,
    amount: float,
    from_account_id: int = 0,
    settled_at: str = "",
) -> dict:
    """Record that money was physically moved into a goal's account (a
    settlement). Updates saved/contribution totals. CONFIRM before calling.

    from_account_id: 0 = backfill (no account debit). Otherwise debits that
    checking/savings account. settled_at: YYYY-MM-DD. Empty = today.
    """
    body: dict = {"amount": abs(amount)}
    if from_account_id:
        body["from_account_id"] = from_account_id
    if settled_at:
        body["settled_at"] = settled_at
    return _post(f"/settlements/goal/{goal_id}", body)


@mcp.tool()
def set_planned_income(month: str, amount: float) -> dict:
    """Set the planned (expected) income for a month. Unassigned is computed
    from this, so changing it shifts how much there is to budget. CONFIRM first.

    month: YYYY-MM-01 or YYYY-MM.
    """
    return _put(f"/monthly-meta/{month}", {"planned_income": abs(amount)})


# ─────────────────────────── AUTH + RUN ───────────────────────────

def _build_app():
    """Streamable HTTP ASGI app with optional token auth.

    Accepts the token two ways so different clients can connect:
      - Authorization: Bearer <token>   (Claude Code, litellm)
      - ?token=<token> query param      (claude.ai custom connectors, which
                                         have no header field in their UI)
    """
    app = mcp.streamable_http_app()
    if AUTH_TOKEN:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse

        class TokenAuth(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                header_ok = request.headers.get("authorization", "") == f"Bearer {AUTH_TOKEN}"
                query_ok = request.query_params.get("token", "") == AUTH_TOKEN
                if not (header_ok or query_ok):
                    return JSONResponse({"error": "unauthorized"}, status_code=401)
                return await call_next(request)

        app.add_middleware(TokenAuth)
    return app


app = _build_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port)
