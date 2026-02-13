import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestUser


def test_migration_status_returns_defaults_when_no_record(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """When no migration record exists, status should return zeros/nulls."""
    # Under test.
    response = requests.get(
        f"{API_SERVER_URL}/admin/opensearch-migration/status",
        headers=admin_user.headers,
    )

    # Postcondition.
    assert response.status_code == 200
    data = response.json()
    assert data["total_chunks_migrated"] == 0
    assert data["created_at"] is None
    assert data["migration_completed_at"] is None


def test_retrieval_status_returns_false_when_no_record(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """When no migration record exists, retrieval should default to disabled."""
    # Under test.
    response = requests.get(
        f"{API_SERVER_URL}/admin/opensearch-migration/retrieval",
        headers=admin_user.headers,
    )

    # Postcondition.
    assert response.status_code == 200
    data = response.json()
    assert data["enable_opensearch_retrieval"] is False


def test_set_and_get_retrieval_status(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """Setting retrieval to True should persist and be readable."""
    # Under test.
    # Enable retrieval.
    response = requests.put(
        f"{API_SERVER_URL}/admin/opensearch-migration/retrieval",
        json={"enable_opensearch_retrieval": True},
        headers=admin_user.headers,
    )

    # Postcondition.
    assert response.status_code == 200
    assert response.json()["enable_opensearch_retrieval"] is True
    # Verify it persisted.
    response = requests.get(
        f"{API_SERVER_URL}/admin/opensearch-migration/retrieval",
        headers=admin_user.headers,
    )
    assert response.status_code == 200
    assert response.json()["enable_opensearch_retrieval"] is True

    # Under test.
    # Disable retrieval.
    response = requests.put(
        f"{API_SERVER_URL}/admin/opensearch-migration/retrieval",
        json={"enable_opensearch_retrieval": False},
        headers=admin_user.headers,
    )

    # Postcondition.
    assert response.status_code == 200
    assert response.json()["enable_opensearch_retrieval"] is False
    # Verify it persisted.
    response = requests.get(
        f"{API_SERVER_URL}/admin/opensearch-migration/retrieval",
        headers=admin_user.headers,
    )
    assert response.status_code == 200
    assert response.json()["enable_opensearch_retrieval"] is False


def test_migration_status_after_record_created(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
) -> None:
    """After toggling retrieval (which creates the record), status should
    return a valid created_at timestamp."""
    # Precondition.
    # Create the record by setting retrieval.
    requests.put(
        f"{API_SERVER_URL}/admin/opensearch-migration/retrieval",
        json={"enable_opensearch_retrieval": False},
        headers=admin_user.headers,
    )

    # Under test.
    response = requests.get(
        f"{API_SERVER_URL}/admin/opensearch-migration/status",
        headers=admin_user.headers,
    )

    # Postcondition.
    assert response.status_code == 200
    data = response.json()
    assert data["total_chunks_migrated"] == 0
    assert data["created_at"] is not None
    assert data["migration_completed_at"] is None


def test_endpoints_require_admin(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,  # noqa: ARG001
) -> None:
    """Endpoints should reject unauthenticated requests."""
    for url in [
        f"{API_SERVER_URL}/admin/opensearch-migration/status",
        f"{API_SERVER_URL}/admin/opensearch-migration/retrieval",
    ]:
        response = requests.get(url)
        assert response.status_code == 403

    response = requests.put(
        f"{API_SERVER_URL}/admin/opensearch-migration/retrieval",
        json={"enable_opensearch_retrieval": True},
    )
    assert response.status_code == 403
