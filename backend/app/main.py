from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import (
    accounts,
    admin,
    bulk,
    dashboard,
    funds,
    inbox,
    plaid,
    suggest,
    templates,
    transactions,
)

app = FastAPI(title="Budget App", version="0.1.0")

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


@app.get("/healthz")
def healthz():
    return {"ok": True}
