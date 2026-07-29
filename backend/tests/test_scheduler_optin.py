"""The daily Plaid sync is opt-in.

Compose sets `ENABLE_SCHEDULER=1`. Everywhere else — tests, scripts, a local
uvicorn — starting the app must not spin up a cron thread that will wake at
06:00 looking for Plaid credentials.
"""
from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from app.main import app


def _apscheduler_threads() -> list[str]:
    return [t.name for t in threading.enumerate() if "apscheduler" in t.name.lower()]


def test_test_client_starts_no_cron_thread(monkeypatch):
    monkeypatch.delenv("ENABLE_SCHEDULER", raising=False)
    before = _apscheduler_threads()
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"ok": True}
        assert _apscheduler_threads() == before


def test_scheduler_starts_only_when_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_SCHEDULER", "1")
    started = []
    monkeypatch.setattr(
        "apscheduler.schedulers.background.BackgroundScheduler.start",
        lambda self, *a, **kw: started.append(self),
    )
    monkeypatch.setattr(
        "apscheduler.schedulers.background.BackgroundScheduler.shutdown",
        lambda self, *a, **kw: None,
    )
    with TestClient(app):
        pass
    assert started, "ENABLE_SCHEDULER=1 did not start the scheduler"
