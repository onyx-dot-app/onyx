"""SCIM matching keys off the provisioned userName, not the account email.

Verifies the identity-decoupling matching semantics against a real database:
the userName filter matches ``scim_user_mapping.scim_username`` (falling back
to the email for legacy mappings), and the mapping lookup used by the
create-path conflict check is case-insensitive.
"""

from uuid import uuid4

import pytest

from ee.onyx.db.scim import ScimDAL
from ee.onyx.server.scim.filtering import ScimFilter, ScimFilterOperator
from tests.external_dependency_unit.db.conftest import ScimUserFactory


def _username_filter(value: str) -> ScimFilter:
    return ScimFilter(
        attribute="userName", operator=ScimFilterOperator.EQUAL, value=value
    )


@pytest.mark.usefixtures("tenant_context")
def test_username_filter_matches_provisioned_username(
    scim_dal: ScimDAL, scim_user_factory: ScimUserFactory
) -> None:
    """When scim_username diverges from the email, the filter follows it."""
    provisioned = f"Provisioned.{uuid4().hex[:8]}@Example.COM"
    user, _ = scim_user_factory(provisioned)

    by_username, total = scim_dal.list_users(
        _username_filter(provisioned.lower()), 1, 10
    )
    assert total == 1
    assert by_username[0][0].id == user.id

    by_email, total = scim_dal.list_users(_username_filter(user.email), 1, 10)
    assert total == 0
    assert by_email == []


@pytest.mark.usefixtures("tenant_context")
def test_username_filter_falls_back_to_email(
    scim_dal: ScimDAL, scim_user_factory: ScimUserFactory
) -> None:
    """Legacy mappings without a scim_username still match by email."""
    user, _ = scim_user_factory(None)

    results, total = scim_dal.list_users(_username_filter(user.email.upper()), 1, 10)
    assert total == 1
    assert results[0][0].id == user.id


@pytest.mark.usefixtures("tenant_context")
def test_get_user_mapping_by_scim_username_is_case_insensitive(
    scim_dal: ScimDAL, scim_user_factory: ScimUserFactory
) -> None:
    provisioned = f"Cased.{uuid4().hex[:8]}@Example.COM"
    user, _ = scim_user_factory(provisioned)

    found = scim_dal.get_user_mapping_by_scim_username(provisioned.lower())
    assert found is not None
    assert found.user_id == user.id

    assert scim_dal.get_user_mapping_by_scim_username(f"missing-{uuid4().hex}") is None
