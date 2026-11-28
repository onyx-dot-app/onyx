"""The model reads the tools in one ranked order (onyx/tools/ordering.py) in
both tool families: the direct tool list, and the functions that the code mode
run tool's description lists. The persona's tool order does not change it."""

import json
from collections.abc import Callable
from contextlib import ExitStack
from uuid import uuid4

import pytest
from pydantic import BaseModel

from onyx.configs.chat_configs import CODE_MODE_ENABLED
from onyx.configs.constants import DocumentSource
from onyx.llm.model_capabilities import ToolFamily
from onyx.llm.override_models import LLMOverride
from onyx.tools.constants import OPEN_URL_TOOL_ID, SEARCH_TOOL_ID
from tests.integration.common_utils.integration_rows import link_persona
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.integration import IntegrationManager
from tests.integration.common_utils.managers.mock_llm import (
    MockLLMScript,
)
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.tool import ToolManager
from tests.integration.common_utils.test_models import DATestLLMProvider, DATestUser
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
)

_PING_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Ping", "description": "Ping", "version": "1.0.0"},
    "servers": [{"url": "https://example.com"}],
    "paths": {
        "/ping": {
            "get": {
                "summary": "Ping the service",
                "operationId": "ping",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}


class _FamilyTools(BaseModel):
    """The names that a model family gets, each list in rank order."""

    code_mode: list[str]
    # Internal search brings postgres_query, and the user's memory tool
    # setting is on by default.
    built_ins: list[str]
    # The user has a skill, so the skill tools are offered.
    skills: list[str]
    agents: list[str]
    question: str


_FAMILIES: dict[ToolFamily, _FamilyTools] = {
    ToolFamily.OPENAI: _FamilyTools(
        code_mode=["execute_code", "wait"],
        built_ins=["internal_search", "open_url", "postgres_query", "add_memory"],
        skills=["skills_list", "skills_read"],
        agents=[
            "spawn_agent",
            "list_agents",
            "interrupt_agent",
            "send_message",
            "wait_agent",
        ],
        question="request_user_input",
    ),
    ToolFamily.CLAUDE: _FamilyTools(
        code_mode=["execute_code", "poll"],
        built_ins=["internal_search", "web_fetch", "postgres_query", "add_memory"],
        skills=["skills_list", "skill"],
        agents=["agent", "list_agents", "interrupt_agent", "send_message"],
        question="ask_user_question",
    ),
}


@pytest.mark.parametrize("tool_family", list(ToolFamily))
def test_the_model_reads_the_tools_in_rank_order(
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    mock_llm_of_family: Callable[[ToolFamily], DATestLLMProvider | None],
    tool_family: ToolFamily,
) -> None:
    family = _FAMILIES[tool_family]
    provider = mock_llm_of_family(tool_family)
    nonce = uuid4().hex
    mock_llm.conversation(
        nonce,
        Reply(text="Done."),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    with ExitStack() as cleanup:
        # internal_search is only offered when a non-default connector exists.
        cc_pair = CCPairManager.create_from_scratch(
            source=DocumentSource.INGESTION_API, user_performing_action=admin_user
        )

        @cleanup.callback
        def _delete_cc_pair() -> None:
            CCPairManager.pause_cc_pair(
                cc_pair=cc_pair, user_performing_action=admin_user
            )
            CCPairManager.delete(cc_pair=cc_pair, user_performing_action=admin_user)

        tool_ids = {
            tool.in_code_tool_id: tool.id
            for tool in ToolManager.list_tools(user_performing_action=admin_user)
        }
        integration_id = IntegrationManager.create(
            {
                "for_organization": True,
                "name": f"ping-{nonce}",
                "description": "Ping a service",
                "auth_mode": "none",
                "auth_method": None,
                "config": {
                    "shape": "openapi",
                    "openapi_document": json.dumps(_PING_SPEC),
                },
            },
            admin_user,
        ).id
        cleanup.callback(
            lambda: IntegrationManager.delete(
                integration_id, admin_user
            ).raise_for_status()
        )
        # The persona lists its tools in reverse rank order.
        persona = PersonaManager.create(
            tool_ids=[tool_ids[OPEN_URL_TOOL_ID], tool_ids[SEARCH_TOOL_ID]],
            user_performing_action=admin_user,
        )

        @cleanup.callback
        def _delete_persona() -> None:
            assert PersonaManager.delete(persona, user_performing_action=admin_user)

        link_persona(persona.id, integration_id, {})
        skill = SkillManager.create_custom(admin_user)
        cleanup.callback(SkillManager.delete_custom, skill, admin_user)
        session = ChatSessionManager.create(
            persona_id=persona.id, user_performing_action=admin_user
        )

        @cleanup.callback
        def _delete_session() -> None:
            assert ChatSessionManager.delete(session, admin_user)

        response = ChatSessionManager.send_message(
            session.id,
            f"Hello. {nonce}",
            admin_user,
            accepts_follow_ups=True,
            llm_override=LLMOverride(
                model_configuration_id=provider.model_configuration_ids[0]
            )
            if provider is not None
            else None,
        )
        assert response.error is None, response.error

        [recorded] = mock_llm.requests_in(nonce)
        definitions = [tool["function"] for tool in recorded.body["tools"]]
        offered = [definition["name"] for definition in definitions]
        custom_name = f"custom__{integration_id}__"
        if not CODE_MODE_ENABLED:
            # The OpenAPI tool is an integration, so it comes last.
            assert offered[:-1] == [
                *family.built_ins,
                *family.skills,
                *family.agents,
                family.question,
            ]
            assert offered[-1].startswith(custom_name)
            return
        assert offered == [*family.code_mode, *family.agents, family.question]
        description = definitions[0]["description"]
        listed = [
            description.index(f"async def {function}(")
            for function in [*family.built_ins, *family.skills]
        ]
        assert listed == sorted(listed)
        # The OpenAPI function is deferred: the program search finds it, and
        # the description only notes that more functions exist.
        assert "More functions are available than the ones in the Functions list" in (
            description
        )
        assert custom_name not in description
