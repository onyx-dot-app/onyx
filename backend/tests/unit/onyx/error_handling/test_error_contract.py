"""Every error the API returns carries a machine-readable error_code.

OnyxError always did (see test_exceptions.py). These are the three paths that
did not: a bare HTTPException, a bare ValueError, and request validation. The
fields each handler returned before are kept, so existing readers of "detail"
and "message" are unaffected.
"""

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.main import log_http_error, validation_exception_handler, value_error_handler


class _Body(BaseModel):
    count: int


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    # Registered exactly as get_application does.
    for status_code in (400, 401, 403, 404, 500):
        app.add_exception_handler(status_code, log_http_error)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ValueError, value_error_handler)

    @app.get("/http-error")
    def _http_error() -> None:
        raise HTTPException(status_code=404, detail="Connector not found")

    @app.get("/dict-detail")
    def _dict_detail() -> None:
        raise HTTPException(status_code=400, detail={"field": "name"})

    @app.get("/value-error")
    def _value_error() -> None:
        raise ValueError("Model 'gpt-9' is not valid for provider_id=3")

    @app.post("/validated")
    def _validated(body: _Body) -> None:  # noqa: ARG001
        return None

    return TestClient(app, raise_server_exceptions=False)


class TestCanonicalCodeForStatus:
    @pytest.mark.parametrize(
        "status_code,expected",
        [
            (400, "BAD_REQUEST"),
            (401, "UNAUTHENTICATED"),
            (403, "UNAUTHORIZED"),
            (404, "NOT_FOUND"),
            (409, "CONFLICT"),
            (422, "VALIDATION_ERROR"),
            (500, "INTERNAL_ERROR"),
            (503, "SERVICE_UNAVAILABLE"),
        ],
    )
    def test_known_statuses(self, status_code: int, expected: str) -> None:
        assert OnyxErrorCode.for_status(status_code).code == expected

    def test_unlisted_statuses_fall_back_by_class(self) -> None:
        assert OnyxErrorCode.for_status(418) is OnyxErrorCode.BAD_REQUEST
        assert OnyxErrorCode.for_status(507) is OnyxErrorCode.INTERNAL_ERROR

    def test_every_mapped_code_agrees_with_its_own_status(self) -> None:
        """A status must not map to a code that reports a different status.

        422 is the deliberate exception. VALIDATION_ERROR is declared 400,
        which is the right default for an OnyxError raise site, and it is still
        the right name for a rejected request body.
        """
        for status_code in (400, 401, 404, 409, 429, 500, 502, 503, 504):
            assert OnyxErrorCode.for_status(status_code).status_code == status_code

        assert OnyxErrorCode.for_status(422) is OnyxErrorCode.VALIDATION_ERROR


class TestHTTPExceptionContract:
    def test_body_carries_code_and_keeps_detail(self, client: TestClient) -> None:
        response = client.get("/http-error")

        assert response.status_code == 404
        assert response.json() == {
            "error_code": "NOT_FOUND",
            "detail": "Connector not found",
        }

    def test_a_non_string_detail_is_left_alone(self, client: TestClient) -> None:
        """detail may be a dict; the code is added beside it, not over it."""
        response = client.get("/dict-detail")

        assert response.status_code == 400
        body: dict[str, Any] = response.json()
        assert body["detail"] == {"field": "name"}
        assert body["error_code"] == "BAD_REQUEST"


class TestValueErrorContract:
    def test_body_gains_a_code_and_keeps_message(self, client: TestClient) -> None:
        response = client.get("/value-error")

        assert response.status_code == 400
        body: dict[str, Any] = response.json()
        # what this handler has always returned
        assert body["message"] == "Model 'gpt-9' is not valid for provider_id=3"
        # what a machine client can now match on
        assert body["error_code"] == "BAD_REQUEST"
        assert body["detail"] == body["message"]


class TestValidationErrorContract:
    def test_body_gains_a_code_and_keeps_its_fields(self, client: TestClient) -> None:
        response = client.post("/validated", json={"count": "not-a-number"})

        assert response.status_code == 422
        body: dict[str, Any] = response.json()
        assert body["status_code"] == 422
        assert body["data"] is None
        assert body["message"]
        assert body["error_code"] == "VALIDATION_ERROR"
        assert body["detail"] == body["message"]
