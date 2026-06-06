"""Docs endpoints must require admin auth (Oneleet pentest finding ON-010).

`/openapi.json`, `/docs` and `/redoc` used to be served to anyone, disclosing
the full API surface. They are now registered behind
``current_curator_or_admin_user`` (see ``onyx.server.api_docs``).
"""

import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

DOCS_PATHS = ["/openapi.json", "/docs", "/redoc"]


@pytest.mark.parametrize("path", DOCS_PATHS)
def test_docs_endpoints_reject_anonymous(path: str) -> None:
    """Without credentials the docs routes must not be readable."""
    response = client.get(f"{API_SERVER_URL}{path}")
    assert response.status_code in (401, 403)


@pytest.mark.parametrize("path", DOCS_PATHS)
def test_docs_endpoints_allow_admin(path: str, admin_user: DATestUser) -> None:
    """A logged-in admin can still reach the docs."""
    response = client.get(f"{API_SERVER_URL}{path}", headers=admin_user.headers)
    assert response.status_code == 200
