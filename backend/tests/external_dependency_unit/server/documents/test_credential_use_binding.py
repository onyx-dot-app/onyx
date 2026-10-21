"""A user may use a credential only when they own it (or it has no owner and
they are an admin), or when they can see it and the config keeps the
credential-bound values of a pair that already uses it. Covers the rule and
each entry point: pairing, draft runs, capability-check overrides, cc-pair
dry runs and edits."""

from collections.abc import Generator
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors import factory
from onyx.connectors.edit_plan.models import CurrentPairState, ProposedPairState
from onyx.connectors.edit_plan.state import (
    fetch_current_pair_state,
    fetch_proposed_credential,
)
from onyx.connectors.factory import (
    assert_user_can_use_credential,
    validate_ccpair_for_user,
)
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    User,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import capability_check_runs
from onyx.server.documents.capability_check_runs import start_cc_pair_draft_check_run
from onyx.server.documents.credential_capabilities import (
    CapabilityCheckRunRequest,
    DraftCheckRunRequest,
    start_draft_check_run,
    trigger_capability_check,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

_SOURCE = DocumentSource.CONFLUENCE
_SITE = "https://acme.atlassian.net"
_OTHER_SITE = "https://attacker.example.com"


def _config(wiki_base: str, space: str = "ENG") -> dict[str, Any]:
    return {"wiki_base": wiki_base, "is_cloud": True, "space": space}


@dataclass
class _Env:
    owner: User
    # Another admin: sees the owner's admin_public credential.
    admin: User
    # Not an admin: sees only their own credentials.
    member: User
    # The owner's admin_public credential ("Admins").
    shared: Credential
    # The owner's private credential ("Only Me").
    private: Credential
    # The pairs that record each credential's bound values.
    pair: ConnectorCredentialPair
    private_pair: ConnectorCredentialPair


def _connector(db_session: Session, config: dict[str, Any]) -> Connector:
    connector = Connector(
        name=f"use-{uuid4().hex[:8]}",
        source=_SOURCE,
        input_type=InputType.POLL,
        connector_specific_config=config,
    )
    db_session.add(connector)
    db_session.flush()
    return connector


def _credential(
    db_session: Session, owner: User | None, *, admin_public: bool = True
) -> Credential:
    credential = Credential(
        name=f"use-{uuid4().hex[:8]}",
        source=_SOURCE,
        credential_json={
            "confluence_username": "bot@acme.com",
            "confluence_access_token": "secret",
        },
        user_id=owner.id if owner else None,
        admin_public=admin_public,
    )
    db_session.add(credential)
    db_session.flush()
    return credential


def _pair(
    db_session: Session, connector: Connector, credential: Credential
) -> ConnectorCredentialPair:
    pair = ConnectorCredentialPair(
        name=f"use-{uuid4().hex[:8]}",
        connector_id=connector.id,
        credential_id=credential.id,
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
    )
    db_session.add(pair)
    db_session.commit()
    return pair


@pytest.fixture
def env(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[_Env, None, None]:
    owner = create_test_user(db_session, "use_owner", is_admin=True)
    admin = create_test_user(db_session, "use_admin", is_admin=True)
    member = create_test_user(db_session, "use_member")

    shared = _credential(db_session, owner)
    pair = _pair(db_session, _connector(db_session, _config(_SITE)), shared)
    private = _credential(db_session, owner, admin_public=False)
    private_pair = _pair(db_session, _connector(db_session, _config(_SITE)), private)

    yield _Env(
        owner=owner,
        admin=admin,
        member=member,
        shared=shared,
        private=private,
        pair=pair,
        private_pair=private_pair,
    )

    db_session.rollback()
    users = [owner, admin, member]
    credential_ids = list(
        db_session.scalars(
            select(Credential.id).where(
                Credential.user_id.in_([user.id for user in users])
            )
        ).all()
    )
    pairs = db_session.scalars(
        select(ConnectorCredentialPair).where(
            ConnectorCredentialPair.credential_id.in_(credential_ids)
        )
    ).all()
    connector_ids = [p.connector_id for p in pairs]
    for p in pairs:
        db_session.delete(p)
    db_session.flush()
    db_session.execute(delete(Connector).where(Connector.id.in_(connector_ids)))
    db_session.execute(delete(Credential).where(Credential.id.in_(credential_ids)))
    db_session.commit()
    delete_test_user(db_session, *users)


def _use(
    db_session: Session,
    user: User,
    credential: Credential,
    config: dict[str, Any] | None,
) -> None:
    assert_user_can_use_credential(
        db_session,
        user=user,
        credential=credential,
        source=_SOURCE,
        connector_specific_config=config,
    )


def _refused(code: OnyxErrorCode, call: Any, *args: Any, **kwargs: Any) -> None:
    with pytest.raises(OnyxError) as exc:
        call(*args, **kwargs)
    assert exc.value.error_code is code


# The rule


def test_owner_uses_any_values(env: _Env, db_session: Session) -> None:
    _use(db_session, env.owner, env.shared, _config(_OTHER_SITE))
    _use(db_session, env.owner, env.private, _config(_OTHER_SITE))


def test_visible_user_keeps_the_bound_values(env: _Env, db_session: Session) -> None:
    # Another space is not a bound field.
    _use(db_session, env.admin, env.shared, _config(_SITE, space="OPS"))


def test_visible_user_cannot_change_the_bound_values(
    env: _Env, db_session: Session
) -> None:
    _refused(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        _use,
        db_session,
        env.admin,
        env.shared,
        _config(_OTHER_SITE),
    )
    # A required bound field left out matches nothing.
    _refused(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        _use,
        db_session,
        env.admin,
        env.shared,
        {"space": "ENG"},
    )


def test_visible_credential_without_a_pair_is_for_its_owner(
    env: _Env, db_session: Session
) -> None:
    unpaired = _credential(db_session, env.owner)
    db_session.commit()

    _use(db_session, env.owner, unpaired, _config(_SITE))
    for config in (_config(_SITE), None):
        _refused(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            _use,
            db_session,
            env.admin,
            unpaired,
            config,
        )


def test_ownerless_credential_is_usable_by_an_admin(
    env: _Env, db_session: Session
) -> None:
    ownerless = _credential(db_session, None)
    db_session.commit()
    try:
        _use(db_session, env.admin, ownerless, _config(_OTHER_SITE))
        _refused(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            _use,
            db_session,
            env.member,
            ownerless,
            _config(_OTHER_SITE),
        )
    finally:
        db_session.delete(ownerless)
        db_session.commit()


def test_credential_not_visible_is_refused(env: _Env, db_session: Session) -> None:
    for user, credential in (
        (env.admin, env.private),
        (env.member, env.shared),
    ):
        _refused(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            _use,
            db_session,
            user,
            credential,
            _config(_SITE),
        )


# The entry points


@pytest.fixture
def no_source_io() -> Generator[MagicMock, None, None]:
    """Stops everything after the rule from reaching the source or a broker."""
    with (
        patch.object(
            factory, "validate_and_record_pairing", return_value=True
        ) as validate,
        patch.object(capability_check_runs.client_app, "send_task"),
        patch.object(capability_check_runs, "send_capability_check_run_task"),
    ):
        yield validate


def test_pairing(env: _Env, db_session: Session, no_source_io: MagicMock) -> None:
    other = _connector(db_session, _config(_OTHER_SITE))
    same = _connector(db_session, _config(_SITE, space="OPS"))
    db_session.commit()

    _refused(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        validate_ccpair_for_user,
        other.id,
        env.shared.id,
        AccessType.PUBLIC,
        db_session,
        user=env.admin,
    )
    no_source_io.assert_not_called()

    assert validate_ccpair_for_user(
        same.id, env.shared.id, AccessType.PUBLIC, db_session, user=env.admin
    )
    assert validate_ccpair_for_user(
        other.id, env.shared.id, AccessType.PUBLIC, db_session, user=env.owner
    )


def _draft_run(credential: Credential, config: dict[str, Any]) -> DraftCheckRunRequest:
    return DraftCheckRunRequest(
        source=_SOURCE,
        credential_id=credential.id,
        draft_key=uuid4().hex,
        form_state=config,
    )


def test_draft_run(
    env: _Env,
    db_session: Session,
    no_source_io: MagicMock,  # noqa: ARG001
) -> None:
    _refused(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        start_draft_check_run,
        _draft_run(env.shared, _config(_OTHER_SITE)),
        user=env.admin,
        db_session=db_session,
    )
    snapshot = start_draft_check_run(
        _draft_run(env.shared, _config(_SITE)),
        user=env.admin,
        db_session=db_session,
    )
    assert snapshot.credential_id == env.shared.id


def test_capability_check_override(
    env: _Env,
    db_session: Session,
    no_source_io: MagicMock,  # noqa: ARG001
) -> None:
    def trigger(
        user: User,
        credential: Credential,
        pair: ConnectorCredentialPair,
        config: dict[str, Any] | None,
    ) -> Any:
        return trigger_capability_check(
            credential.id,
            CapabilityCheckRunRequest(
                connector_id=pair.connector_id, connector_specific_config=config
            ),
            user=user,
            db_session=db_session,
        )

    # A global manager sees the pairing but not the private credential: an
    # override no longer falls back to the unfiltered fetch.
    _refused(
        OnyxErrorCode.CREDENTIAL_NOT_FOUND,
        trigger,
        env.admin,
        env.private,
        env.private_pair,
        _config(_SITE),
    )
    # The stored config is the pair's own use.
    trigger(env.admin, env.private, env.private_pair, None)

    _refused(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        trigger,
        env.admin,
        env.shared,
        env.pair,
        _config(_OTHER_SITE),
    )
    trigger(env.admin, env.shared, env.pair, _config(_SITE, space="OPS"))


def _proposal(current: CurrentPairState, **update: Any) -> ProposedPairState:
    return ProposedPairState.model_validate({**current.model_dump(), **update})


def test_edit_and_dry_run(
    env: _Env,
    db_session: Session,
    no_source_io: MagicMock,  # noqa: ARG001
) -> None:
    # The admin owns a pair and proposes moving it to the owner's credential.
    own = _credential(db_session, env.admin)
    own_pair = _pair(db_session, _connector(db_session, _config(_OTHER_SITE)), own)
    current = fetch_current_pair_state(db_session, own_pair.id)

    def propose(config: dict[str, Any], credential: Credential) -> Credential:
        return fetch_proposed_credential(
            db_session,
            user=env.admin,
            current=current,
            proposed=_proposal(
                current, connector_specific_config=config, credential_id=credential.id
            ),
        )

    _refused(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        propose,
        _config(_OTHER_SITE),
        env.shared,
    )
    assert propose(_config(_SITE), env.shared).id == env.shared.id
    # Their own credential takes any values.
    assert propose(_config("https://new.atlassian.net"), own).id == own.id

    def dry_run(config: dict[str, Any]) -> Any:
        return start_cc_pair_draft_check_run(
            db_session,
            user=env.admin,
            cc_pair_id=own_pair.id,
            proposed_credential=env.shared,
            access_type=AccessType.PUBLIC,
            connector_specific_config=config,
        )

    _refused(OnyxErrorCode.INSUFFICIENT_PERMISSIONS, dry_run, _config(_OTHER_SITE))
    assert dry_run(_config(_SITE)).credential_id == env.shared.id


def test_pair_editor_keeps_the_pairs_values_without_seeing_the_credential(
    env: _Env, db_session: Session
) -> None:
    # An admin edits the private credential's pair without seeing the credential.
    current = fetch_current_pair_state(db_session, env.private_pair.id)

    def propose(config: dict[str, Any]) -> Credential:
        return fetch_proposed_credential(
            db_session,
            user=env.admin,
            current=current,
            proposed=_proposal(current, connector_specific_config=config),
        )

    assert propose(_config(_SITE, space="OPS")).id == env.private.id
    _refused(OnyxErrorCode.CREDENTIAL_NOT_FOUND, propose, _config(_OTHER_SITE))


def test_fields_derived_from_the_credential_are_not_compared(
    env: _Env, db_session: Session
) -> None:
    # Drive's credential_kind comes from the credential, and pairs saved before
    # the field existed do not store it.
    drive = Credential(
        name=f"use-{uuid4().hex[:8]}",
        source=DocumentSource.GOOGLE_DRIVE,
        credential_json={"google_tokens": "{}"},
        user_id=env.owner.id,
        admin_public=True,
    )
    db_session.add(drive)
    db_session.flush()
    connector = Connector(
        name=f"use-{uuid4().hex[:8]}",
        source=DocumentSource.GOOGLE_DRIVE,
        input_type=InputType.POLL,
        connector_specific_config={"include_shared_drives": True},
    )
    db_session.add(connector)
    db_session.flush()
    _pair(db_session, connector, drive)

    for kind in ("oauth", "service_account", None):
        assert_user_can_use_credential(
            db_session,
            user=env.admin,
            credential=drive,
            source=DocumentSource.GOOGLE_DRIVE,
            connector_specific_config={"credential_kind": kind},
        )
