"""Permission scoping for Craft provider selection (real DB).

``fetch_all_supported_build_llm_providers`` must respect LLM-provider access
control (is_public / group membership) so a user never gets a sandbox keyed
with a provider's API key they aren't entitled to use.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.llm import fetch_first_accessible_llm_provider_by_type
from onyx.db.llm import remove_llm_provider
from onyx.db.llm import upsert_llm_provider
from onyx.db.models import LLMProvider
from onyx.db.models import LLMProvider__Persona
from onyx.db.models import LLMProvider__UserGroup
from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.server.features.build.db.build_session import (
    fetch_all_supported_build_llm_providers,
)
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from tests.external_dependency_unit.craft.db_helpers import add_user_to_group
from tests.external_dependency_unit.craft.db_helpers import make_group
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.db.agent_sharing_helpers import create_test_persona


def _make_group_restricted_anthropic_provider(
    db_session: Session, group_id: int
) -> int:
    provider = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=f"craft-access-test-{uuid4().hex[:8]}",
            provider="anthropic",
            api_key="sk-ant-not-used",
            api_key_changed=True,
            is_public=False,
            groups=[group_id],
            model_configurations=[
                ModelConfigurationUpsertRequest(name="claude-opus-4-7", is_visible=True)
            ],
        ),
        db_session=db_session,
    )
    db_session.commit()
    return provider.id


def _has_provider(db_session: Session, user: User, provider_id: int) -> bool:
    return any(
        view.id == provider_id
        for view in fetch_all_supported_build_llm_providers(db_session, user)
    )


def test_group_restricted_provider_scoped_by_membership(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    group = make_group(db_session)
    member = make_user(db_session)
    add_user_to_group(db_session, member, group)
    non_member = make_user(db_session)
    admin = make_user(db_session, role=UserRole.ADMIN)
    db_session.commit()

    provider_id = _make_group_restricted_anthropic_provider(db_session, group.id)
    try:
        # Group member and admin (admins bypass group restrictions) can use it.
        assert _has_provider(db_session, member, provider_id)
        assert _has_provider(db_session, admin, provider_id)
        # A non-member must NOT get it — otherwise their sandbox would be keyed
        # with a provider they can't access.
        assert not _has_provider(db_session, non_member, provider_id)
    finally:
        remove_llm_provider(db_session, provider_id)
        db_session.commit()


def _make_llm_provider(
    db_session: Session,
    *,
    provider_type: str,
    api_key: str,
    is_public: bool,
) -> LLMProvider:
    provider = LLMProvider(
        name=f"sandbox-credential-{uuid4().hex[:8]}",
        provider=provider_type,
        api_key=api_key,
        is_public=is_public,
    )
    db_session.add(provider)
    db_session.flush()
    return provider


def _delete_llm_providers(db_session: Session, provider_ids: list[int]) -> None:
    db_session.execute(
        delete(LLMProvider__UserGroup).where(
            LLMProvider__UserGroup.llm_provider_id.in_(provider_ids)
        )
    )
    db_session.execute(
        delete(LLMProvider__Persona).where(
            LLMProvider__Persona.llm_provider_id.in_(provider_ids)
        )
    )
    db_session.execute(delete(LLMProvider).where(LLMProvider.id.in_(provider_ids)))
    db_session.commit()


def test_focused_provider_fetch_is_ordered_and_access_scoped(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    member = make_user(db_session)
    non_member = make_user(db_session)
    admin = make_user(db_session, role=UserRole.ADMIN)
    group = make_group(db_session)
    add_user_to_group(db_session, member, group)

    public_provider_type = f"sandbox-public-{uuid4().hex}"
    first_public_provider = _make_llm_provider(
        db_session,
        provider_type=public_provider_type,
        api_key="sk-first",
        is_public=True,
    )
    second_public_provider = _make_llm_provider(
        db_session,
        provider_type=public_provider_type,
        api_key="sk-second",
        is_public=True,
    )

    group_provider_type = f"sandbox-group-{uuid4().hex}"
    group_provider = _make_llm_provider(
        db_session,
        provider_type=group_provider_type,
        api_key="sk-group",
        is_public=False,
    )
    db_session.add(
        LLMProvider__UserGroup(
            llm_provider_id=group_provider.id,
            user_group_id=group.id,
        )
    )

    locked_provider_type = f"sandbox-locked-{uuid4().hex}"
    locked_provider = _make_llm_provider(
        db_session,
        provider_type=locked_provider_type,
        api_key="sk-locked",
        is_public=False,
    )

    persona = create_test_persona(db_session, owner=admin)
    persona_provider_type = f"sandbox-persona-{uuid4().hex}"
    persona_provider = _make_llm_provider(
        db_session,
        provider_type=persona_provider_type,
        api_key="sk-persona",
        is_public=True,
    )
    db_session.add(
        LLMProvider__Persona(
            llm_provider_id=persona_provider.id,
            persona_id=persona.id,
        )
    )
    db_session.commit()

    provider_ids = [
        first_public_provider.id,
        second_public_provider.id,
        group_provider.id,
        locked_provider.id,
        persona_provider.id,
    ]
    try:
        selected = fetch_first_accessible_llm_provider_by_type(
            public_provider_type, non_member, db_session
        )
        assert selected is not None
        assert selected.id == first_public_provider.id
        assert selected.api_key is not None
        assert selected.api_key.get_value(apply_mask=False) == "sk-first"

        assert (
            fetch_first_accessible_llm_provider_by_type(
                group_provider_type, member, db_session
            )
            is not None
        )
        assert (
            fetch_first_accessible_llm_provider_by_type(
                group_provider_type, non_member, db_session
            )
            is None
        )
        assert (
            fetch_first_accessible_llm_provider_by_type(
                group_provider_type, admin, db_session
            )
            is not None
        )

        assert (
            fetch_first_accessible_llm_provider_by_type(
                locked_provider_type, non_member, db_session
            )
            is None
        )
        assert (
            fetch_first_accessible_llm_provider_by_type(
                locked_provider_type, admin, db_session
            )
            is not None
        )

        # Craft has no persona context, so persona restrictions apply even to
        # public providers and administrators.
        assert (
            fetch_first_accessible_llm_provider_by_type(
                persona_provider_type, member, db_session
            )
            is None
        )
        assert (
            fetch_first_accessible_llm_provider_by_type(
                persona_provider_type, admin, db_session
            )
            is None
        )
    finally:
        _delete_llm_providers(db_session, provider_ids)
