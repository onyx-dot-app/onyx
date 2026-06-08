"""Tests for sandbox PAT infrastructure (PR 1: PAT provisioning, reuse, expiry, filtering)."""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
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
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.craft._test_helpers import default_llm_config


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

    def test_mismatched_hash_revokes_and_mints_new(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Sandbox,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Sandbox.encrypted_pat points at a token whose hash does NOT match any
        valid CRAFT PAT in the DB. The mismatched DB PAT is revoked and a fresh
        one is minted; ``encrypted_pat`` is rewritten to the new raw token.
        """
        # Mint a DB-only CRAFT PAT that the sandbox does NOT know about.
        db_only_pat, db_only_raw = create_pat(
            db_session=db_session,
            user_id=test_user.id,
            name=f"craft-{test_user.id}",
            expiration_days=30,
            pat_type=PatType.CRAFT,
        )
        db_session.commit()

        # Point the sandbox at a *different* raw token (the hashes will not
        # match what's in the DB). This is the "mismatched hash" scenario:
        # the encrypted_pat references some prior token that the DB no longer
        # has, or vice versa.
        bogus_raw = "onyx_pat_bogus_does_not_correspond_to_db_row"
        sandbox.encrypted_pat = bogus_raw  # ty: ignore[invalid-assignment]
        db_session.commit()

        new_raw = ensure_sandbox_pat(db_session, sandbox, test_user)
        db_session.commit()

        # The new token is different from both the bogus reference and the
        # pre-existing DB-only PAT.
        assert new_raw != bogus_raw
        assert new_raw != db_only_raw
        assert new_raw.startswith("onyx_pat_")

        # The previously-existing DB PAT was revoked.
        db_session.refresh(db_only_pat)
        assert db_only_pat.is_revoked is True
        assert db_only_pat.expires_at is not None
        assert db_only_pat.expires_at <= datetime.now(timezone.utc)

        # Sandbox.encrypted_pat is now the new raw token.
        assert sandbox.encrypted_pat is not None
        assert sandbox.encrypted_pat.get_value(apply_mask=False) == new_raw

        # The new PAT is a valid CRAFT PAT for this user.
        new_hashed = hash_pat(new_raw)
        new_pat = (
            db_session.query(PersonalAccessToken)
            .filter_by(hashed_token=new_hashed)
            .one()
        )
        assert new_pat.pat_type == PatType.CRAFT
        assert new_pat.user_id == test_user.id
        assert new_pat.is_revoked is False

    def test_multiple_stale_pats_all_revoked(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Sandbox,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Regression for SHA 6cf482d8c0: when the DB contains multiple stale
        valid CRAFT PATs for the same user (e.g. from earlier provisioning
        attempts that did not revoke their predecessors), ``ensure_sandbox_pat``
        must revoke ALL of them — not just one — and mint a single new PAT.
        """
        stale_pat_1, stale_raw_1 = create_pat(
            db_session=db_session,
            user_id=test_user.id,
            name=f"craft-{test_user.id}",
            expiration_days=30,
            pat_type=PatType.CRAFT,
        )
        stale_pat_2, stale_raw_2 = create_pat(
            db_session=db_session,
            user_id=test_user.id,
            name=f"craft-{test_user.id}",
            expiration_days=30,
            pat_type=PatType.CRAFT,
        )
        db_session.commit()

        # Two distinct valid CRAFT PATs exist for the user before we call
        # ensure_sandbox_pat.
        pre_valid = (
            db_session.query(PersonalAccessToken)
            .filter_by(user_id=test_user.id, pat_type=PatType.CRAFT)
            .filter(
                (PersonalAccessToken.expires_at.is_(None))
                | (PersonalAccessToken.expires_at > datetime.now(timezone.utc))
            )
            .all()
        )
        assert len(pre_valid) == 2

        new_raw = ensure_sandbox_pat(db_session, sandbox, test_user)
        db_session.commit()

        assert new_raw not in {stale_raw_1, stale_raw_2}

        # Both stale PATs are revoked.
        db_session.refresh(stale_pat_1)
        db_session.refresh(stale_pat_2)
        assert stale_pat_1.is_revoked is True
        assert stale_pat_2.is_revoked is True
        now = datetime.now(timezone.utc)
        assert stale_pat_1.expires_at is not None and stale_pat_1.expires_at <= now
        assert stale_pat_2.expires_at is not None and stale_pat_2.expires_at <= now

        # Only the newly-minted PAT is a valid CRAFT PAT for the user.
        post_valid = (
            db_session.query(PersonalAccessToken)
            .filter_by(user_id=test_user.id, pat_type=PatType.CRAFT)
            .filter(
                (PersonalAccessToken.expires_at.is_(None))
                | (PersonalAccessToken.expires_at > datetime.now(timezone.utc))
            )
            .all()
        )
        assert len(post_valid) == 1
        assert post_valid[0].hashed_token == hash_pat(new_raw)
        assert post_valid[0].is_revoked is False

    def test_provision_without_pat_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``KubernetesSandboxManager.provision(onyx_pat="")`` must raise
        ValueError before issuing any K8s mutation — the empty-PAT guard is
        the last line of defence against pods coming up unauthenticated.

        We bypass ``__init__`` (no live cluster needed in this layer) and
        stub ``_pod_exists_and_healthy`` to return False so the guard is
        actually reached.
        """
        manager = object.__new__(KubernetesSandboxManager)

        def _no_pod(
            self: KubernetesSandboxManager,  # noqa: ARG001
            pod_name: str,  # noqa: ARG001
        ) -> bool:
            return False

        monkeypatch.setattr(
            KubernetesSandboxManager, "_pod_exists_and_healthy", _no_pod
        )

        llm_config = default_llm_config()

        with pytest.raises(ValueError, match="onyx_pat"):
            manager.provision(
                sandbox_id=uuid4(),
                user_id=uuid4(),
                tenant_id=TEST_TENANT_ID,
                llm_config=llm_config,
                onyx_pat="",
            )

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "known: no background PAT refresh on long-lived sandboxes; expired "
            "PAT inside a running pod stays expired until next provision. "
            "Masked today by idle-cleanup-at-1h; visible if idle timeout is "
            "ever raised past 25 days."
        ),
    )
    def test_pat_refreshes_on_reprovision_after_expiry(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Sandbox,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """A long-lived sandbox (no reprovision) should still see a fresh PAT
        injected into its pod after the original PAT expires.

        There is no background refresh mechanism today: ``ensure_sandbox_pat``
        runs on the provisioning path; it does not push new PATs into already-
        running pods. This test asserts the (currently absent) behaviour so
        that if a refresher is added, the xfail flips and the regression
        surfaces.
        """
        # Mint and expire the initial PAT.
        token_1 = ensure_sandbox_pat(db_session, sandbox, test_user)
        db_session.commit()

        pat_1 = (
            db_session.query(PersonalAccessToken)
            .filter_by(hashed_token=hash_pat(token_1))
            .one()
        )
        pat_1.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db_session.commit()

        # No reprovision happens here — we deliberately do NOT call
        # ensure_sandbox_pat again. A hypothetical background refresher
        # would update Sandbox.encrypted_pat to a fresh, unexpired token.
        # Until that refresher exists, this assertion fails (xfail strict).
        db_session.refresh(sandbox)
        assert sandbox.encrypted_pat is not None
        current_raw: Any = sandbox.encrypted_pat.get_value(apply_mask=False)
        current_pat = (
            db_session.query(PersonalAccessToken)
            .filter_by(hashed_token=hash_pat(current_raw))
            .one()
        )
        assert current_pat.expires_at is not None
        assert current_pat.expires_at > datetime.now(timezone.utc), (
            "Sandbox.encrypted_pat should reference a non-expired PAT even "
            "without an explicit reprovision call."
        )
