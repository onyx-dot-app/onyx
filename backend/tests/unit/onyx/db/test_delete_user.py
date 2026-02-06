from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import UUID
from uuid import uuid4

from onyx.db.models import DocumentSet
from onyx.db.models import DocumentSet__User
from onyx.db.models import Persona
from onyx.db.models import Persona__User
from onyx.db.models import SamlAccount
from onyx.db.models import User__UserGroup
from onyx.db.users import delete_user_from_db


def _mock_user(
    user_id: UUID | None = None, email: str = "test@example.com"
) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid4()
    user.email = email
    user.oauth_accounts = []
    return user


def _make_query_chain() -> MagicMock:
    """Returns a mock that supports .filter(...).delete() and .filter(...).update(...)"""
    chain = MagicMock()
    chain.filter.return_value = chain
    return chain


@patch("onyx.db.users.remove_user_from_invited_users")
@patch(
    "onyx.db.users.fetch_ee_implementation_or_noop",
    return_value=lambda **_kwargs: None,
)
def test_delete_user_nulls_out_document_set_ownership(
    _mock_ee: Any, _mock_remove_invited: Any
) -> None:
    user = _mock_user()
    db_session = MagicMock()

    query_chains: dict[type, MagicMock] = {}

    def query_side_effect(model: type) -> MagicMock:
        if model not in query_chains:
            query_chains[model] = _make_query_chain()
        return query_chains[model]

    db_session.query.side_effect = query_side_effect

    delete_user_from_db(user, db_session)

    # Verify DocumentSet.user_id is nulled out (update, not delete)
    doc_set_chain = query_chains[DocumentSet]
    doc_set_chain.filter.assert_called()
    doc_set_chain.filter.return_value.update.assert_called_once_with(
        {DocumentSet.user_id: None}
    )

    # Verify Persona.user_id is nulled out (update, not delete)
    persona_chain = query_chains[Persona]
    persona_chain.filter.assert_called()
    persona_chain.filter.return_value.update.assert_called_once_with(
        {Persona.user_id: None}
    )


@patch("onyx.db.users.remove_user_from_invited_users")
@patch(
    "onyx.db.users.fetch_ee_implementation_or_noop",
    return_value=lambda **_kwargs: None,
)
def test_delete_user_cleans_up_join_tables(
    _mock_ee: Any, _mock_remove_invited: Any
) -> None:
    user = _mock_user()
    db_session = MagicMock()

    query_chains: dict[type, MagicMock] = {}

    def query_side_effect(model: type) -> MagicMock:
        if model not in query_chains:
            query_chains[model] = _make_query_chain()
        return query_chains[model]

    db_session.query.side_effect = query_side_effect

    delete_user_from_db(user, db_session)

    # Join tables should be deleted (not updated)
    for model in [DocumentSet__User, Persona__User, User__UserGroup, SamlAccount]:
        chain = query_chains[model]
        chain.filter.return_value.delete.assert_called_once()


@patch("onyx.db.users.remove_user_from_invited_users")
@patch(
    "onyx.db.users.fetch_ee_implementation_or_noop",
    return_value=lambda **_kwargs: None,
)
def test_delete_user_commits_and_removes_invited(
    _mock_ee: Any, mock_remove_invited: Any
) -> None:
    user = _mock_user(email="deleted@example.com")
    db_session = MagicMock()
    db_session.query.return_value = _make_query_chain()

    delete_user_from_db(user, db_session)

    db_session.delete.assert_called_once_with(user)
    db_session.commit.assert_called_once()
    mock_remove_invited.assert_called_once_with("deleted@example.com")


@patch("onyx.db.users.remove_user_from_invited_users")
@patch(
    "onyx.db.users.fetch_ee_implementation_or_noop",
    return_value=lambda **_kwargs: None,
)
def test_delete_user_deletes_oauth_accounts(
    _mock_ee: Any, _mock_remove_invited: Any
) -> None:
    user = _mock_user()
    oauth1 = MagicMock()
    oauth2 = MagicMock()
    user.oauth_accounts = [oauth1, oauth2]
    db_session = MagicMock()
    db_session.query.return_value = _make_query_chain()

    delete_user_from_db(user, db_session)

    db_session.delete.assert_any_call(oauth1)
    db_session.delete.assert_any_call(oauth2)
