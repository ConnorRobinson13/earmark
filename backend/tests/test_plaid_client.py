import json

import pytest
from app.services.plaid_client import PlaidApiClient, PlaidApiError
from plaid.exceptions import ApiException


class RecordingPlaidApi:
    def __init__(self):
        self.request = None
        self.kwargs = None

    def link_token_create(self, request, **kwargs):
        self.request = request
        self.kwargs = kwargs
        return {"link_token": "update-link-stub"}

    def item_get(self, request, **kwargs):
        self.request = request
        self.kwargs = kwargs
        return {"item": {"error": {"error_code": "ITEM_LOGIN_REQUIRED"}}}


def test_update_link_token_uses_existing_access_token_without_products():
    api = RecordingPlaidApi()
    client = PlaidApiClient(api)

    result = client.create_update_link_token("access-token-for-existing-item")

    assert result == "update-link-stub"
    assert api.request.access_token == "access-token-for-existing-item"
    assert "products" not in api.request
    assert api.kwargs["_request_timeout"] == (3.05, 8.0)


def test_item_status_reads_the_plaid_error_code():
    api = RecordingPlaidApi()
    client = PlaidApiClient(api)

    assert client.item_error_code("status-access-token") == "ITEM_LOGIN_REQUIRED"
    assert api.request.access_token == "status-access-token"
    assert api.kwargs["_request_timeout"] == (1.0, 2.0)


def test_sdk_item_login_error_is_normalized_without_exposing_raw_response():
    class FailingPlaidApi:
        def link_token_create(self, request, **kwargs):
            error = ApiException(status=400, reason="Bad Request")
            error.body = json.dumps(
                {
                    "error_code": "ITEM_LOGIN_REQUIRED",
                    "error_message": "Please reauthenticate",
                    "request_id": "plaid-request-id",
                }
            )
            raise error

    client = PlaidApiClient(FailingPlaidApi())

    with pytest.raises(PlaidApiError) as caught:
        client.create_update_link_token("private-access-token")

    assert caught.value.error_code == "ITEM_LOGIN_REQUIRED"
    assert caught.value.status == 400
    assert caught.value.request_id == "plaid-request-id"
    assert caught.value.__suppress_context__ is True
    assert "private-access-token" not in str(caught.value)
    assert "plaid-request-id" not in str(caught.value)


def test_transport_timeouts_become_sanitized_plaid_errors():
    class OfflinePlaidApi:
        def link_token_create(self, request, **kwargs):
            raise TimeoutError("private transport details")

    client = PlaidApiClient(OfflinePlaidApi())

    with pytest.raises(PlaidApiError) as caught:
        client.create_update_link_token("private-access-token")

    assert caught.value.error_code == "PLAID_TRANSPORT_ERROR"
    assert caught.value.status is None
    assert "private transport details" not in str(caught.value)
    assert "private-access-token" not in str(caught.value)
