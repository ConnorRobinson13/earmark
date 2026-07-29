import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .db import new_session
from .month import InvalidMonth
from .routers import (
    accounts,
    admin,
    bulk,
    cashflow,
    dashboard,
    funds,
    inbox,
    monthly_meta,
    networth,
    paydays,
    plaid,
    settlements,
    suggest,
    templates,
    transactions,
)

log = logging.getLogger(__name__)


def _daily_sync_job():
    """Pull Plaid transactions + refresh balances. Scheduled at 06:00 local."""
    from .routers.plaid import run_sync  # local import — keep startup light
    db = new_session()
    try:
        added = run_sync(db)
        log.info("daily sync: added %d transactions", added)
    except Exception:
        log.exception("daily sync failed")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Opt-in: the compose stack sets ENABLE_SCHEDULER=1. Anywhere else — tests,
    # scripts, a local uvicorn — constructing the app must not start a cron
    # thread that would go hunting for Plaid credentials at 06:00.
    if os.environ.get("ENABLE_SCHEDULER") != "1":
        log.info("scheduler disabled (set ENABLE_SCHEDULER=1 to enable)")
        yield
        return
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    sched = BackgroundScheduler(timezone=os.environ.get("TZ", "America/Chicago"))
    sched.add_job(
        _daily_sync_job,
        CronTrigger(hour=6, minute=0),
        id="daily_plaid_sync",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    sched.start()
    log.info("scheduler started: daily Plaid sync at 06:00 %s", sched.timezone)
    try:
        yield
    finally:
        sched.shutdown(wait=False)


app = FastAPI(title="Earmark", version="0.1.0", lifespan=lifespan)


@app.exception_handler(InvalidMonth)
def _invalid_month(_request: Request, exc: InvalidMonth) -> JSONResponse:
    """One 400 for an unreadable month, wherever it was read.

    Registered centrally so no router carries its own try/except — that is what
    let six copies of the parse block drift apart in the first place.
    """
    return JSONResponse(status_code=400, content={"detail": str(exc)})


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(funds.router)
app.include_router(transactions.router)
app.include_router(accounts.router)
app.include_router(dashboard.router)
app.include_router(templates.router)
app.include_router(suggest.router)
app.include_router(inbox.router)
app.include_router(plaid.router)
app.include_router(admin.router)
app.include_router(bulk.router)
app.include_router(settlements.router)
app.include_router(monthly_meta.router)
app.include_router(networth.router)
app.include_router(cashflow.router)
app.include_router(paydays.router)


@app.get("/healthz")
def healthz():
    return {"ok": True}
