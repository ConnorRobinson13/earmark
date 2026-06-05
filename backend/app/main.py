import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import SessionLocal
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
    db = SessionLocal()
    try:
        added = run_sync(db)
        log.info("daily sync: added %d transactions", added)
    except Exception:
        log.exception("daily sync failed")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Skip scheduler in test/CI runs to avoid spurious cron threads
    if os.environ.get("DISABLE_SCHEDULER") == "1":
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


app = FastAPI(title="Budget App", version="0.1.0", lifespan=lifespan)

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
