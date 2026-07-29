"""Importing the models package must be inert.

This guards the seam that makes the rest of the backend testable. If importing
`app.models` reads the environment, opens `.env`, or builds an engine, then no
part of the backend can be exercised without the full compose stack — which is
exactly how this repo ended up with zero tests.

The probe runs in a subprocess so the tracking hooks are installed before the
very first `app` import, and so nothing it does leaks into the rest of the
suite. Its working directory is a scratch directory holding a decoy `.env`, so
that a settings import would be caught reading it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

# Every environment variable the app's own Settings would read. None of these
# may be touched by importing models.
APP_ENV_KEYS = {
    "DATABASE_URL",
    "OLLAMA_URL",
    "EMBEDDING_MODEL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "PLAID_CLIENT_ID",
    "PLAID_SECRET",
    "PLAID_ENV",
    "PLAID_SYNC_FLOOR_DATE",
}

PROBE = r"""
import builtins, json, os, socket, sys

opened = []
_real_open = builtins.open
def tracking_open(file, *a, **kw):
    opened.append(str(file))
    return _real_open(file, *a, **kw)
builtins.open = tracking_open

connected = []
_real_connect = socket.socket.connect
def tracking_connect(self, address):
    connected.append(str(address))
    return _real_connect(self, address)
socket.socket.connect = tracking_connect

# Two ways to read the environment: by name, and by slurping the whole mapping
# (which is how pydantic-settings does it). Record both.
by_key, bulk = [], []
class TrackingEnviron(dict):
    def __getitem__(self, key):
        by_key.append(key)
        return super().__getitem__(key)
    def get(self, key, default=None):
        by_key.append(key)
        return super().get(key, default)
    def __contains__(self, key):
        by_key.append(key)
        return super().__contains__(key)
    def keys(self):
        bulk.append("keys")
        return super().keys()
    def items(self):
        bulk.append("items")
        return super().items()
    def values(self):
        bulk.append("values")
        return super().values()
    def __iter__(self):
        bulk.append("iter")
        return super().__iter__()
os.environ = TrackingEnviron(os.environ)

import app.models  # noqa: F401
from app import db

builtins.open = _real_open
print("@@" + json.dumps({
    "by_key": by_key,
    "bulk": sorted(set(bulk)),
    "opened": opened,
    "connected": connected,
    "config_imported": "app.config" in sys.modules,
    "engine_built": db.is_configured(),
}))
"""


@pytest.fixture(scope="module")
def probe(tmp_path_factory) -> dict:
    cwd = tmp_path_factory.mktemp("decoy")
    (cwd / ".env").write_text("DATABASE_URL=postgresql+psycopg://decoy/decoy\n")

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(BACKEND), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
    )
    proc = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"probe failed:\n{proc.stderr}"
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("@@"))
    return json.loads(line[2:])


def test_importing_models_reads_no_environment(probe):
    touched = APP_ENV_KEYS & {k.upper() for k in probe["by_key"]}
    assert not touched, f"importing app.models read {sorted(touched)}"
    assert not probe["bulk"], (
        f"importing app.models slurped the whole environment via {probe['bulk']}"
    )


def test_importing_models_does_not_read_the_dotenv_file(probe):
    opened = [p for p in probe["opened"] if Path(p).name == ".env"]
    assert not opened, f"importing app.models opened {opened}"


def test_importing_models_opens_no_sockets(probe):
    assert not probe["connected"], f"importing app.models connected to {probe['connected']}"


def test_importing_models_pulls_in_neither_settings_nor_an_engine(probe):
    assert not probe["config_imported"], "app.models imported app.config"
    assert not probe["engine_built"], "importing app.models built an engine"
