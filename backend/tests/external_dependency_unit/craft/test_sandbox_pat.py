"""Tests for sandbox PAT infrastructure (PR 1: PAT provisioning, reuse, expiry, filtering)."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.auth.pat import hash_pat
from onyx.db.enums import PatType
from onyx.db.enums import SandboxStatus
from onyx.db.models import PersonalAccessToken
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.db.pat import create_pat
from onyx.db.pat import list_user_pats
from onyx.server.features.build.db.sandbox import ensure_sandbox_pat


@pytest.fixture()
def sandbox(db_session: Session, test_user: User) -> Sandbox:
    """Create a test sandbox for PAT tests."""
    sb = Sandbox(
        id=uuid4(),
        user_id=test_user.id,
        status=SandboxStatus.RUNNING,
    )
    db_session.add(sb)
    db_session.commit()
    db_session.refresh(sb)
    return sb


class TestEnsureSandboxPat:
    def test_first_call_mints_pat(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Sandbox,
    ) -> None:
        raw_token = ensure_sandbox_pat(db_session, sandbox, test_user)

        assert raw_token.startswith("onyx_pat_")
        assert sandbox.encrypted_pat is not None
        decrypted = sandbox.encrypted_pat.get_value(apply_mask=False)
        assert decrypted == raw_token

        hashed = hash_pat(raw_token)
        pat = db_session.query(PersonalAccessToken).filter_by(hashed_token=hashed).one()
        assert pat.pat_type == PatType.CRAFT
        assert pat.user_id == test_user.id

    def test_second_call_reuses_token(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Sandbox,
    ) -> None:
        token_1 = ensure_sandbox_pat(db_session, sandbox, test_user)
        token_2 = ensure_sandbox_pat(db_session, sandbox, test_user)

        assert token_1 == token_2

        craft_pats = (
            db_session.query(PersonalAccessToken)
            .filter_by(user_id=test_user.id, pat_type=PatType.CRAFT)
            .filter(
                (PersonalAccessToken.expires_at.is_(None))
                | (PersonalAccessToken.expires_at > datetime.now(timezone.utc))
            )
            .all()
        )
        assert len(craft_pats) == 1

    def test_expired_token_triggers_remint(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Sandbox,
    ) -> None:
        token_1 = ensure_sandbox_pat(db_session, sandbox, test_user)

        hashed = hash_pat(token_1)
        pat = db_session.query(PersonalAccessToken).filter_by(hashed_token=hashed).one()
        pat.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()

        token_2 = ensure_sandbox_pat(db_session, sandbox, test_user)

        assert token_2 != token_1
        assert token_2.startswith("onyx_pat_")

        new_hashed = hash_pat(token_2)
        new_pat = (
            db_session.query(PersonalAccessToken)
            .filter_by(hashed_token=new_hashed)
            .one()
        )
        assert new_pat.pat_type == PatType.CRAFT
        assert new_pat.expires_at is not None
        assert new_pat.expires_at > datetime.now(timezone.utc)

    def test_user_pat_filter_excludes_craft_pat(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Sandbox,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        ensure_sandbox_pat(db_session, sandbox, test_user)

        create_pat(
            db_session=db_session,
            user_id=test_user.id,
            name="my-user-pat",
            expiration_days=30,
        )

        user_pats = list_user_pats(db_session, test_user.id, pat_type=PatType.USER)
        assert len(user_pats) == 1
        assert user_pats[0].name == "my-user-pat"

        all_pats = list_user_pats(db_session, test_user.id)
        assert any(p.pat_type == PatType.CRAFT for p in all_pats)

    def test_pat_type_defaults_to_user(
        self,
        db_session: Session,
        test_user: User,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        pat, _token = create_pat(
            db_session=db_session,
            user_id=test_user.id,
            name="default-type-test",
            expiration_days=30,
        )
        assert pat.pat_type == PatType.USER
