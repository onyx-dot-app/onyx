"""Permission scoping for Craft provider selection (real DB).

``fetch_all_supported_build_llm_providers`` must respect LLM-provider access
control (is_public / group membership) so a user never gets a sandbox keyed
with a provider's API key they aren't entitled to use.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.llm import remove_llm_provider
from onyx.db.llm import upsert_llm_provider
from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.server.features.build.db.build_session import (
    fetch_all_supported_build_llm_providers,
)
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from tests.external_dependency_unit.craft._test_helpers import add_user_to_group
from tests.external_dependency_unit.craft._test_helpers import make_group
from tests.external_dependency_unit.craft._test_helpers import make_user


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
