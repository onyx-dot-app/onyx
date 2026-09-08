"""fetch_github_repo_access against real users, groups, and cc-pairs.

The unit tests mock `get_connector_credential_pairs_for_user`, so the one
predicate deciding who can obtain a decrypted PAT is never exercised there.
This decides whether an LLM-driven agent reads a private repository, so it is
worth running against the real query.
"""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.credentials import fetch_github_repo_access
from onyx.db.enums import AccessType, Permission
from onyx.db.models import (
    ConnectorCredentialPair,
    User,
    User__UserGroup,
    UserGroup,
    UserGroup__ConnectorCredentialPair,
)
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import make_cc_pair

TOKEN = "ghp_test_token"
REPO = "repo"

pytestmark = pytest.mark.usefixtures("enable_ee")


@pytest.fixture
def owner() -> str:
    """Unique per test so parallel runs cannot match each other's pairs."""
    return f"org-{uuid4().hex[:8]}"


def _private_github_pair(db_session: Session, owner: str) -> ConnectorCredentialPair:
    pair = make_cc_pair(
        db_session,
        source=DocumentSource.GITHUB,
        connector_specific_config={
            "repo_owner": owner,
            "repositories": REPO,
            "include_code_files": True,
        },
        credential_json={"github_access_token": TOKEN},
    )
    pair.access_type = AccessType.PRIVATE
    db_session.commit()
    return pair


def _user_in_group_with(
    db_session: Session, pair: ConnectorCredentialPair, email_prefix: str
) -> User:
    user = _plain_user(db_session, email_prefix)
    group = UserGroup(name=f"repo-access-{uuid4().hex[:12]}")
    db_session.add(group)
    db_session.flush()
    db_session.add(User__UserGroup(user_id=user.id, user_group_id=group.id))
    db_session.add(
        UserGroup__ConnectorCredentialPair(
            user_group_id=group.id, cc_pair_id=pair.id, is_current=True
        )
    )
    db_session.commit()
    return user


def _plain_user(
    db_session: Session, email_prefix: str, *permissions: Permission
) -> User:
    user = create_test_user(db_session, email_prefix)
    user.effective_permissions = [permission.value for permission in permissions]
    db_session.commit()
    return user


def test_group_member_receives_the_connector_token(
    db_session: Session, owner: str
) -> None:
    pair = _private_github_pair(db_session, owner)
    member = _user_in_group_with(db_session, pair, "repo-access-member")

    access = fetch_github_repo_access(
        db_session=db_session, repo_owner=owner, repo_name=REPO, user=member
    )

    assert access is not None
    assert access.token == TOKEN


def test_user_outside_the_group_is_refused(db_session: Session, owner: str) -> None:
    _private_github_pair(db_session, owner)
    outsider = _plain_user(db_session, "repo-access-outsider")

    assert (
        fetch_github_repo_access(
            db_session=db_session, repo_owner=owner, repo_name=REPO, user=outsider
        )
        is None
    )


def test_curator_permissions_do_not_grant_the_token(
    db_session: Session, owner: str
) -> None:
    """MANAGE_DOCUMENT_SETS implies READ_CONNECTORS, which makes the cc-pair
    listing return every pair. Listing a connector is not holding its PAT."""
    _private_github_pair(db_session, owner)
    curator = _plain_user(
        db_session, "repo-access-curator", Permission.MANAGE_DOCUMENT_SETS
    )

    assert (
        fetch_github_repo_access(
            db_session=db_session, repo_owner=owner, repo_name=REPO, user=curator
        )
        is None
    )
