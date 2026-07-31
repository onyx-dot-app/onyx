"""Guards that claiming an address revokes it as anyone else's alias.

A prior address keeps granting its former holder access to documents whose
indexed ACLs still name it. That grant is only safe while the address belongs
to nobody else, so every `User` email write has to release it.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection
from sqlalchemy.orm import attributes

from onyx.db import models
from onyx.db.models import User


def test_a_new_user_releases_the_address_from_every_former_holder() -> None:
    user = User(email="Recycled@Example.com", hashed_password="unused")
    connection = MagicMock(spec=Connection)

    models._release_inserted_user_email(MagicMock(), connection, user)

    release = connection.execute.call_args.args[0]
    sql = str(
        release.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "array_remove" in sql
    assert "prior_emails @>" in sql
    assert "'recycled@example.com'" in sql
    # A fresh row has no id to exclude, so every holder is released.
    assert '"user".id !=' not in sql


def test_a_rename_releases_the_address_without_touching_the_renamer() -> None:
    user = User(id=uuid4(), email="old@example.com", hashed_password="unused")
    attributes.set_committed_value(user, "email", "old@example.com")
    user.email = "Taken@Example.com"
    connection = MagicMock(spec=Connection)

    models._release_updated_user_email(MagicMock(), connection, user)

    release = connection.execute.call_args.args[0]
    sql = str(
        release.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "array_remove" in sql
    assert "'taken@example.com'" in sql
    assert '"user".id !=' in sql


def test_an_unchanged_email_releases_nothing() -> None:
    user = User(id=uuid4(), email="same@example.com", hashed_password="unused")
    attributes.set_committed_value(user, "email", "same@example.com")
    connection = MagicMock(spec=Connection)

    models._release_updated_user_email(MagicMock(), connection, user)

    connection.execute.assert_not_called()


def test_both_listeners_are_registered() -> None:
    """An unregistered listener leaves a stale alias granting access, and nothing
    else in the flush path would notice."""
    assert event.contains(User, "before_insert", models._release_inserted_user_email)
    assert event.contains(User, "before_update", models._release_updated_user_email)


def test_an_inserted_address_is_released_from_everyone() -> None:
    user = User(email="claimed@example.com", hashed_password="unused")
    connection = MagicMock(spec=Connection)

    with patch.object(models, "_release_prior_email_claim") as release:
        models._release_inserted_user_email(MagicMock(), connection, user)

    release.assert_called_once_with("claimed@example.com", connection)
