"""Guards the alias release against real rows rather than mocked calls.

A prior address keeps granting its former holder access to documents whose
indexed ACLs still name it. That grant is only safe while the address belongs to
nobody else, so claiming it has to strip it from every other user in the same
flush. These read the other user's row back from Postgres, which is the only way
to catch the listener firing on the wrong statement or the `array_remove` and
`contains` predicates disagreeing about case.
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import AccountType
from onyx.db.models import User
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user


@pytest.fixture
def users_to_clean(db_session: Session) -> Generator[list[User], None, None]:
    created: list[User] = []
    yield created
    for user in created:
        delete_test_user(db_session, user)
    db_session.commit()


def _aliased_user(db_session: Session, prefix: str, prior_emails: list[str]) -> User:
    user = create_test_user(db_session, prefix)
    user.prior_emails = prior_emails
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.mark.usefixtures("tenant_context")
def test_inserting_a_user_strips_the_address_from_other_aliases(
    db_session: Session, users_to_clean: list[User]
) -> None:
    retired = f"retired_{uuid4().hex[:8]}@example.com"
    former_holder = _aliased_user(db_session, "former", [retired])
    users_to_clean.append(former_holder)

    claimant = User(
        id=uuid4(),
        email=retired,
        hashed_password="unused",
        is_active=True,
        is_verified=True,
        account_type=AccountType.STANDARD,
    )
    db_session.add(claimant)
    users_to_clean.append(claimant)
    db_session.commit()

    db_session.refresh(former_holder)
    assert former_holder.prior_emails == []


@pytest.mark.usefixtures("tenant_context")
def test_renaming_onto_the_address_strips_it_from_other_aliases(
    db_session: Session, users_to_clean: list[User]
) -> None:
    retired = f"retired_{uuid4().hex[:8]}@example.com"
    former_holder = _aliased_user(db_session, "former", [retired])
    claimant = create_test_user(db_session, "claimant")
    users_to_clean.extend([former_holder, claimant])

    claimant.email = retired
    db_session.commit()

    db_session.refresh(former_holder)
    assert former_holder.prior_emails == []


@pytest.mark.usefixtures("tenant_context")
def test_a_claim_keeps_the_claimants_own_aliases(
    db_session: Session, users_to_clean: list[User]
) -> None:
    """The update excludes the claiming row, or a user renaming back to an
    address they already hold as an alias would erase their own history."""
    retired = f"retired_{uuid4().hex[:8]}@example.com"
    readopted = f"readopted_{uuid4().hex[:8]}@example.com"
    claimant = _aliased_user(db_session, "claimant", [retired, readopted])
    users_to_clean.append(claimant)

    claimant.email = readopted
    db_session.commit()

    db_session.refresh(claimant)
    assert claimant.prior_emails == [retired, readopted]


@pytest.mark.usefixtures("tenant_context")
def test_only_the_claimed_address_is_released(
    db_session: Session, users_to_clean: list[User]
) -> None:
    claimed = f"claimed_{uuid4().hex[:8]}@example.com"
    untouched = f"untouched_{uuid4().hex[:8]}@example.com"
    former_holder = _aliased_user(db_session, "former", [untouched, claimed])
    claimant = create_test_user(db_session, "claimant")
    users_to_clean.extend([former_holder, claimant])

    claimant.email = claimed
    db_session.commit()

    db_session.refresh(former_holder)
    assert former_holder.prior_emails == [untouched]


@pytest.mark.usefixtures("tenant_context")
def test_the_release_is_case_insensitive(
    db_session: Session, users_to_clean: list[User]
) -> None:
    """Aliases are stored lowercased, so a claim arriving in mixed case still
    has to match. `@validates` normalizes the claimant, and the release
    lowercases before comparing."""
    retired = f"retired_{uuid4().hex[:8]}@example.com"
    former_holder = _aliased_user(db_session, "former", [retired])
    claimant = create_test_user(db_session, "claimant")
    users_to_clean.extend([former_holder, claimant])

    claimant.email = retired.upper()
    db_session.commit()

    db_session.refresh(former_holder)
    assert former_holder.prior_emails == []
    db_session.refresh(claimant)
    assert claimant.email == retired


@pytest.mark.usefixtures("tenant_context")
def test_an_unrelated_rename_releases_nothing(
    db_session: Session, users_to_clean: list[User]
) -> None:
    retired = f"retired_{uuid4().hex[:8]}@example.com"
    former_holder = _aliased_user(db_session, "former", [retired])
    claimant = create_test_user(db_session, "claimant")
    users_to_clean.extend([former_holder, claimant])

    claimant.email = f"elsewhere_{uuid4().hex[:8]}@example.com"
    db_session.commit()

    db_session.refresh(former_holder)
    assert former_holder.prior_emails == [retired]
