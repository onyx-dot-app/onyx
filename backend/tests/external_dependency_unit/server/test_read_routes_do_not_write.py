"""Read routes reached by basic users must not change shared state."""

from uuid import uuid4

import pytest
from mcp.types import Tool as MCPLibTool
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPServerStatus,
    MCPTransport,
)
from onyx.db.llm import remove_llm_provider, upsert_llm_provider
from onyx.db.mcp import create_mcp_server__no_commit, update_mcp_server__no_commit
from onyx.db.models import MCPServer, Persona
from onyx.llm.constants import LlmProviderNames
from onyx.server.features.mcp import api as mcp_api
from onyx.server.features.persona.api import get_persona
from onyx.server.manage.api_token.models import NewApiToken
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user


def test_user_tool_listing_keeps_admin_disconnect(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = create_test_user(db_session, "mcp_owner", is_admin=True)
    viewer = create_test_user(db_session, "mcp_viewer")
    server = create_mcp_server__no_commit(
        owner_email=admin.email,
        name=f"disconnected-{uuid4().hex[:8]}",
        description=None,
        server_url=f"https://mcp-{uuid4().hex[:8]}.example.com/mcp",
        auth_type=MCPAuthenticationType.NONE,
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
        db_session=db_session,
        is_public=True,
    )
    update_mcp_server__no_commit(
        server_id=server.id,
        db_session=db_session,
        status=MCPServerStatus.DISCONNECTED,
    )
    db_session.commit()
    monkeypatch.setattr(
        mcp_api,
        "discover_mcp_tools",
        lambda *_args, **_kwargs: [MCPLibTool(name="lookup", inputSchema={})],
    )

    try:
        response = mcp_api.user_list_mcp_tools_by_id(server.id, db_session, viewer)

        assert [tool.name for tool in response.tools] == ["lookup"]
        db_session.expire_all()
        stored = db_session.get(MCPServer, server.id)
        assert stored is not None
        assert stored.status == MCPServerStatus.DISCONNECTED
    finally:
        db_session.rollback()
        db_session.execute(delete(MCPServer).where(MCPServer.id == server.id))
        delete_test_user(db_session, admin, viewer)
        db_session.commit()


def test_viewer_outside_provider_group_keeps_agent_model_pin(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    owner = create_test_user(db_session, "pin_owner", is_admin=True)
    viewer = create_test_user(db_session, "pin_viewer")
    provider = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=f"restricted-{uuid4().hex[:8]}",
            provider=LlmProviderNames.OPENAI,
            api_key=NewApiToken(value="sk-test-00000000000000000000000000000000000000"),
            is_public=False,
            model_configurations=[
                ModelConfigurationUpsertRequest(name="gpt-4o-mini", is_visible=True)
            ],
        ),
        db_session=db_session,
    )
    pinned_id = provider.model_configurations[0].id
    assert pinned_id is not None
    persona = Persona(
        name=f"pinned-{uuid4().hex[:8]}",
        description="pinned model",
        user_id=owner.id,
        is_public=True,
        default_model_configuration_id=pinned_id,
    )
    db_session.add(persona)
    db_session.commit()

    try:
        snapshot = get_persona(persona.id, viewer, db_session)

        # The viewer cannot use the model, so the response hides it.
        assert snapshot.default_model_configuration_id is None
        db_session.expire_all()
        stored = db_session.get(Persona, persona.id)
        assert stored is not None
        assert stored.default_model_configuration_id == pinned_id
        assert (
            get_persona(persona.id, owner, db_session).default_model_configuration_id
            == pinned_id
        )
    finally:
        db_session.rollback()
        db_session.execute(delete(Persona).where(Persona.id == persona.id))
        db_session.commit()
        remove_llm_provider(db_session, provider.id)
        delete_test_user(db_session, owner, viewer)
        db_session.commit()
