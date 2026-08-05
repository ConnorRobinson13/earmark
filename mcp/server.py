"""Earmark MCP server — "talk to your money".

Wraps the budget-app FastAPI (never the DB directly) so all the EveryDollar-style
balance math, paired-transaction safety, and goal/settlement logic stay in one
place. Exposes a curated set of conversational tools over Streamable HTTP.

The tools forward; they don't decide. Every value a caller supplies reaches the
backend as given — signs included — and every rejection comes back in the
backend's own words. Re-deriving a rule here means having two answers to the
same question, and the wrong one wins silently because nothing errors.

Env:
  BUDGET_API_URL   base URL of the backend API   (default http://backend:8000)
  MCP_AUTH_TOKEN   bearer token clients must send (default "" = no auth, local only)
  MCP_HOST/MCP_PORT  bind address                 (default 0.0.0.0:9000)
"""
from __future__ import annotations

import json
import os
import re
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


# One connection pool for the process, and the seam the tests swap out: a client
# on a mock transport exercises every tool without a backend behind it.
_http = httpx.Client(base_url=API, timeout=30.0)


def _detail(response: httpx.Response) -> str:
    """The most useful thing an error response has to say.

    FastAPI puts a plain sentence under `detail` for its own rejections and a
    list of per-field errors there for a schema violation. Anything else — a
    proxy failing in front of the backend — may not be JSON at all.
    """
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason_phrase
    if isinstance(payload, dict) and "detail" in payload:
        payload = payload["detail"]
    return payload if isinstance(payload, str) else json.dumps(payload)


class BudgetApiError(RuntimeError):
    """A non-2xx from the backend, quoting what the backend said about it.

    `raise_for_status()` reports the status code and nothing else, which turns an
    explained rejection ("amount must be positive") into a bare 400 the model
    can't act on. A raised exception is the only channel back to the caller, so
    the body rides along with the status.
    """

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"budget API returned {response.status_code}: {_detail(response)}")


def _request(
    method: str, path: str, *, params: dict | None = None, body: dict | None = None
) -> Any:
    response = _http.request(method, path, params=params, json=body)
    if response.is_error:
        raise BudgetApiError(response)
    return response.json() if response.content else {}


def _get(path: str, params: dict | None = None) -> Any:
    return _request("GET", path, params=params)


def _post(path: str, body: dict) -> Any:
    return _request("POST", path, body=body)


def _put(path: str, body: dict) -> Any:
    return _request("PUT", path, body=body)


#: Word for word `app.month.INVALID_MONTH_DETAIL`, under the same name, so a
#: caller gets one sentence about months whichever side rejects theirs. Copied
#: rather than imported because this server ships as its own container with only
#: `server.py` in it (see `Dockerfile`) — there is no import path to the backend
#: from here. `tests/test_server.py` fails if the two strings drift apart.
INVALID_MONTH_DETAIL = "month must be YYYY-MM or YYYY-MM-DD"

_MONTH_FORM = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$")


def _month_first(raw: str) -> date:
    """The first of the month `raw` names, from either form the backend accepts.

    Months belong to the backend (`app.month`), and every month-taking endpoint
    reads both `YYYY-MM` and `YYYY-MM-DD`, so tools that take a month hand it
    over untouched. The exception is `/transactions/assign`, which takes a
    *date* — choosing that date means knowing which month was named, and there's
    no import path to `app.month` from this container to ask. So this is the one
    month rule restated here: the same two forms, landing on the same first of
    the month, refusing what the backend would refuse rather than posting a date
    that parses but means something else.
    """
    form = _MONTH_FORM.match(raw)
    if not form:
        raise ValueError(INVALID_MONTH_DETAIL)
    try:
        named = date(int(form[1]), int(form[2]), int(form[3] or 1))
    except ValueError as exc:  # month 13, February 30th, …
        raise ValueError(INVALID_MONTH_DETAIL) from exc
    return named.replace(day=1)


# The two fund kinds, copied rather than imported — `FundKind` lives in
# `backend/app/models.py` and this container has no path to it. Copied the same
# way the month message above is, and held to the original by the same kind of
# test, so a kind added there can't be missing here in silence.
OPERATIONAL_KIND = "operational"
GOAL_KIND = "goal"


# `list_funds` and `list_goals` are one fund list cut two ways, and each used to
# spell its own cut out. Both cuts below ask what a fund is rather than what it
# is not, so a kind neither knows is listed by neither tool — the model gets a
# short list it can query about, not a fund filed under a heading that is wrong.
def _operational(funds: list[dict]) -> list[dict]:
    """The monthly spending buckets in a fund list."""
    return [f for f in funds if f["kind"] == OPERATIONAL_KIND]


def _goals(funds: list[dict]) -> list[dict]:
    """The long-term buckets in a fund list — savings, debts, contribution caps."""
    return [f for f in funds if f["kind"] == GOAL_KIND]


# ─────────────────────────── READ TOOLS ───────────────────────────

@mcp.tool()
def financial_overview(month: str = "") -> dict:
    """Snapshot of the budget for a month: unassigned money, planned vs actual
    income, net cash, spent, saved, and every fund with its balance.

    month: YYYY-MM or YYYY-MM-DD. Empty = current month.
    """
    return _get("/dashboard", {"month": month} if month else None)


@mcp.tool()
def list_funds(month: str = "") -> list:
    """All operational spending funds with their assigned/spent/balance.

    month: YYYY-MM or YYYY-MM-DD. Empty = current month. The assigned and spent
    figures are scoped to that month.
    """
    data = _get("/dashboard", {"month": month} if month else None)
    return _operational(data["funds"])


@mcp.tool()
def list_goals() -> list:
    """All goals with progress. Savings goals track a balance; contribution
    goals (Roth/HSA/401k) track contribution_ytd against an annual target.

    Current month only — unlike `list_funds` this takes no month, because the
    endpoint behind it has no month parameter and always reports the month we're
    in. For an earlier month's goal figures use `financial_overview(month)`,
    which reports every fund.
    """
    return _goals(_get("/funds"))


@mcp.tool()
def search_transactions(
    start: str = "",
    end: str = "",
    merchant: str = "",
    fund_id: int | None = None,
    type: str = "",
    min_amount: float | None = None,
    max_amount: float | None = None,
) -> dict:
    """Search transactions for analytical questions ("how much on coffee since
    March"). Returns matching rows + summary (net, total_outflow, total_inflow).

    start/end: YYYY-MM-DD inclusive. merchant: case-insensitive substring.
    type: expense | income | assignment | transfer.
    min_amount/max_amount: bounds on how big the amount is — the filter ignores
    sign, so 5..50 matches a $12 expense and a $12 refund alike. To separate the
    two, read the returned amounts (negative = money out of a fund) or the
    summary's total_outflow / total_inflow.
    Omit anything you don't want to filter on; empty string and null both mean
    "no filter", and 0 is a real bound rather than an omission.
    """
    supplied = {
        "start": start,
        "end": end,
        "merchant": merchant,
        "fund_id": fund_id,
        "type": type,
        "min_amount": min_amount,
        "max_amount": max_amount,
    }
    # Presence, not truthiness: `max_amount=0` asks for nothing but zero-amount
    # rows, and dropping it returned everything — the opposite of the request.
    return _get(
        "/transactions/search",
        {k: v for k, v in supplied.items() if v is not None and v != ""},
    )


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
    their backing account. month: YYYY-MM or YYYY-MM-DD. Empty = current month."""
    return _get("/settlements/pending", {"month": month} if month else None)


@mcp.tool()
def project_retirement(
    current_age: int,
    retire_age: int,
    annual_return_pct: float = 8.0,
    monthly_contribution: float = 0.0,
    contribution_growth_pct: float = 0.0,
    inflation_pct: float = 0.0,
) -> dict:
    """Project investment net worth at retirement. Compounds the CURRENT
    investment-account total plus monthly contributions at the given annual
    return, one year at a time.

    The backend works this out — the same endpoint the net-worth page reads, so
    a question asked here and the same question asked on the page come back with
    the same number. This tool used to compound the series itself, and its copy
    escalated nothing and ignored inflation, so the two answers disagreed.

    Returns `starting_balance`, `total_contributed`, `compounded_growth`,
    `final_nominal`, `final_real`, and a `series` of one point per year. Every
    amount comes back twice over: `nominal` is future dollars, `real` is the
    same money in today's, and the two are equal when inflation_pct is 0.

    annual_return_pct: nominal return on the whole balance, compounded yearly.
    monthly_contribution: what goes in each month of the FIRST year.
    contribution_growth_pct: how much that grows each year — raises. 0 = flat.
    inflation_pct: what the deflation to today's dollars assumes. 0 = no
    deflation, which makes every `real` equal to its `nominal`.
    """
    return _get("/retirement/projection", {
        "current_age": current_age,
        "retire_age": retire_age,
        "annual_return_pct": annual_return_pct,
        "monthly_contribution": monthly_contribution,
        "contribution_growth_pct": contribution_growth_pct,
        "inflation_pct": inflation_pct,
    })


# ─────────────────────────── WRITE TOOLS ───────────────────────────
# These mutate the ledger. Confirm the amount + target with the user in plain
# language BEFORE calling — there is no undo from the chat side.

@mcp.tool()
def assign_to_fund(fund_id: int, amount: float, month: str = "") -> dict:
    """Assign money from Unassigned to a fund (budgeting move). CONFIRM the
    fund and amount with the user before calling — this changes the budget.

    amount: positive to add to the fund, negative to pull back to Unassigned.
    month: YYYY-MM or YYYY-MM-DD. Empty = current month. An assignment in the
    current month is dated today; any other month is dated its first day, so it
    counts toward the month you named rather than the month you're in.
    """
    # One reading of the clock for the whole assignment. Sampling it per use put
    # three `date.today()` calls in two lines, and a call straddling midnight on
    # the first of a month compared one month against the next.
    today = date.today()
    current = today.replace(day=1)
    target = _month_first(month) if month else current
    dated = today if target == current else target
    return _post("/transactions/assign", {
        "fund_id": fund_id,
        "amount": amount,
        "date": dated.isoformat(),
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
    amount: positive number — `type` sets the direction, so pick it
    deliberately. A negative amount is rejected, not reinterpreted.
    txn_date: YYYY-MM-DD. Empty = today.
    """
    return _post("/transactions/quick-add", {
        "fund_id": fund_id,
        "amount": amount,
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

    amount: how much actually moved, positive.
    from_account_id: 0 = backfill (no account debit). Otherwise debits that
    checking/savings account. settled_at: YYYY-MM-DD. Empty = today.
    """
    body: dict = {"amount": amount}
    if from_account_id:
        body["from_account_id"] = from_account_id
    if settled_at:
        body["settled_at"] = settled_at
    return _post(f"/settlements/goal/{goal_id}", body)


@mcp.tool()
def set_planned_income(month: str, amount: float) -> dict:
    """Set the planned (expected) income for a month. Unassigned is computed
    from this, so changing it shifts how much there is to budget. CONFIRM first.

    month: YYYY-MM or YYYY-MM-DD — a day inside a month names that month.
    amount: the income expected that month. Zero is allowed (a month can plan on
    none); a negative one is rejected, since Unassigned is computed from this.
    """
    return _put(f"/monthly-meta/{month}", {"planned_income": amount})


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
