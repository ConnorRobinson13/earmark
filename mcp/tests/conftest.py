"""Test fixtures: the tools, pointed at a stand-in backend.

The MCP server owns no state and no business logic — every tool is a request to
the FastAPI backend. So what these tests check is the request: its URL, its
query string, its body. That means the interesting fixture is a fake API that
records what arrives rather than a real one, and `server._http` is the seam it
swaps in through.

No network, no compose stack, no database: `pytest` here needs nothing running.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

# `server.py` sits next to this directory, not on the path by default.
MCP_DIR = Path(__file__).resolve().parents[1]
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

import server  # noqa: E402


class FakeApi:
    """Records the requests the tools make; answers with whatever it's told to.

    Defaults to an empty 200 so a test that only cares about what was *sent*
    doesn't have to describe a response it never looks at.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self._status = 200
        self._payload: object = {}

    def replies(self, status: int, payload: object) -> None:
        """Answer the next request(s) with this status and JSON body.

        `payload=None` means no body at all — a gateway failing in front of the
        backend, which is the one error that arrives with nothing to quote.
        """
        self._status = status
        self._payload = payload

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._payload is None:
            return httpx.Response(self._status)
        return httpx.Response(self._status, json=self._payload)

    @property
    def request(self) -> httpx.Request:
        """The one request that was made — fails loudly if there wasn't exactly one."""
        assert len(self.requests) == 1, f"expected 1 request, got {len(self.requests)}"
        return self.requests[0]

    @property
    def params(self) -> httpx.QueryParams:
        return self.request.url.params

    @property
    def body(self) -> dict:
        return json.loads(self.request.content)


@pytest.fixture()
def api(monkeypatch) -> FakeApi:
    fake = FakeApi()
    monkeypatch.setattr(
        server,
        "_http",
        httpx.Client(base_url=server.API, transport=httpx.MockTransport(fake._handle)),
    )
    return fake
