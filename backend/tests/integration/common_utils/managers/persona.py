from uuid import UUID
from uuid import uuid4

import requests

from onyx.context.search.enums import RecencyBiasSetting
from onyx.server.features.persona.models import FullPersonaSnapshot
from onyx.server.features.persona.models import PersonaUpsertRequest
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestPersona
from tests.integration.common_utils.test_models import DATestPersonaLabel
from tests.integration.common_utils.test_models import DATestUser


class PersonaManager:
    @staticmethod
    def create(
        name: str | None = None,
        description: str | None = None,
        system_prompt: str | None = None,
        task_prompt: str | None = None,
        include_citations: bool = False,
        num_chunks: float = 5,
        llm_relevance_filter: bool = True,
        is_public: bool = True,
        llm_filter_extraction: bool = True,
        recency_bias: RecencyBiasSetting = RecencyBiasSetting.AUTO,
        datetime_aware: bool = False,
        prompt_ids: list[int] | None = None,
        document_set_ids: list[int] | None = None,
        tool_ids: list[int] | None = None,
        llm_model_provider_override: str | None = None,
        llm_model_version_override: str | None = None,
        users: list[str] | None = None,
        groups: list[int] | None = None,
        label_ids: list[int] | None = None,
        user_performing_action: DATestUser | None = None,
    ) -> DATestPersona:
        name = name or f"test-persona-{uuid4()}"
        description = description or f"Description for {name}"
        system_prompt = system_prompt or f"System prompt for {name}"
        task_prompt = task_prompt or f"Task prompt for {name}"

        persona_creation_request = PersonaUpsertRequest(
            name=name,
            description=description,
            system_prompt=system_prompt,
            task_prompt=task_prompt,
            datetime_aware=datetime_aware,
            include_citations=include_citations,
            num_chunks=num_chunks,
            llm_relevance_filter=llm_relevance_filter,
            is_public=is_public,
            llm_filter_extraction=llm_filter_extraction,
            recency_bias=recency_bias,
            prompt_ids=prompt_ids or [0],
            document_set_ids=document_set_ids or [],
            tool_ids=tool_ids or [],
            llm_model_provider_override=llm_model_provider_override,
            llm_model_version_override=llm_model_version_override,
            users=[UUID(user) for user in (users or [])],
            groups=groups or [],
            label_ids=label_ids or [],
        )

        response = requests.post(
            f"{API_SERVER_URL}/persona",
            json=persona_creation_request.model_dump(mode="json"),
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        persona_data = response.json()

        return DATestPersona(
            id=persona_data["id"],
            name=name,
            description=description,
            num_chunks=num_chunks,
            llm_relevance_filter=llm_relevance_filter,
            is_public=is_public,
            llm_filter_extraction=llm_filter_extraction,
            recency_bias=recency_bias,
            prompt_ids=prompt_ids or [],
            document_set_ids=document_set_ids or [],
            tool_ids=tool_ids or [],
            llm_model_provider_override=llm_model_provider_override,
            llm_model_version_override=llm_model_version_override,
            users=users or [],
            groups=groups or [],
            label_ids=label_ids or [],
        )

    @staticmethod
    def edit(
        persona: DATestPersona,
        name: str | None = None,
        description: str | None = None,
        system_prompt: str | None = None,
        task_prompt: str | None = None,
        include_citations: bool = False,
        num_chunks: float | None = None,
        llm_relevance_filter: bool | None = None,
        is_public: bool | None = None,
        llm_filter_extraction: bool | None = None,
        recency_bias: RecencyBiasSetting | None = None,
        datetime_aware: bool = False,
        prompt_ids: list[int] | None = None,
        document_set_ids: list[int] | None = None,
        tool_ids: list[int] | None = None,
        llm_model_provider_override: str | None = None,
        llm_model_version_override: str | None = None,
        users: list[str] | None = None,
        groups: list[int] | None = None,
        label_ids: list[int] | None = None,
        user_performing_action: DATestUser | None = None,
    ) -> DATestPersona:
        system_prompt = system_prompt or f"System prompt for {persona.name}"
        task_prompt = task_prompt or f"Task prompt for {persona.name}"

        persona_update_request = PersonaUpsertRequest(
            name=name or persona.name,
            description=description or persona.description,
            system_prompt=system_prompt,
            task_prompt=task_prompt,
            datetime_aware=datetime_aware,
            include_citations=include_citations,
            num_chunks=num_chunks or persona.num_chunks,
            llm_relevance_filter=llm_relevance_filter or persona.llm_relevance_filter,
            is_public=is_public or persona.is_public,
            llm_filter_extraction=llm_filter_extraction
            or persona.llm_filter_extraction,
            recency_bias=recency_bias or persona.recency_bias,
            prompt_ids=prompt_ids or persona.prompt_ids,
            document_set_ids=document_set_ids or persona.document_set_ids,
            tool_ids=tool_ids or persona.tool_ids,
            llm_model_provider_override=llm_model_provider_override
            or persona.llm_model_provider_override,
            llm_model_version_override=llm_model_version_override
            or persona.llm_model_version_override,
            users=[UUID(user) for user in (users or persona.users)],
            groups=groups or persona.groups,
            label_ids=label_ids or persona.label_ids,
        )

        response = requests.patch(
            f"{API_SERVER_URL}/persona/{persona.id}",
            json=persona_update_request.model_dump(mode="json"),
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        updated_persona_data = response.json()

        return DATestPersona(
            id=updated_persona_data["id"],
            name=updated_persona_data["name"],
            description=updated_persona_data["description"],
            num_chunks=updated_persona_data["num_chunks"],
            llm_relevance_filter=updated_persona_data["llm_relevance_filter"],
            is_public=updated_persona_data["is_public"],
            llm_filter_extraction=updated_persona_data["llm_filter_extraction"],
            recency_bias=recency_bias or persona.recency_bias,
            prompt_ids=[prompt["id"] for prompt in updated_persona_data["prompts"]],
            document_set_ids=updated_persona_data["document_sets"],
            tool_ids=updated_persona_data["tools"],
            llm_model_provider_override=updated_persona_data[
                "llm_model_provider_override"
            ],
            llm_model_version_override=updated_persona_data[
                "llm_model_version_override"
            ],
            users=[user["email"] for user in updated_persona_data["users"]],
            groups=updated_persona_data["groups"],
            label_ids=updated_persona_data["labels"],
        )

    @staticmethod
    def get_all(
        user_performing_action: DATestUser | None = None,
    ) -> list[FullPersonaSnapshot]:
        response = requests.get(
            f"{API_SERVER_URL}/admin/persona",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return [FullPersonaSnapshot(**persona) for persona in response.json()]

    @staticmethod
    def get_one(
        persona_id: int,
        user_performing_action: DATestUser | None = None,
    ) -> list[FullPersonaSnapshot]:
        response = requests.get(
            f"{API_SERVER_URL}/persona/{persona_id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return [FullPersonaSnapshot(**response.json())]

    @staticmethod
    def verify(
        persona: DATestPersona,
        user_performing_action: DATestUser | None = None,
    ) -> bool:
        all_personas = PersonaManager.get_one(
            persona_id=persona.id,
            user_performing_action=user_performing_action,
        )
        for fetched_persona in all_personas:
            if fetched_persona.id == persona.id:
                return (
                    fetched_persona.name == persona.name
                    and fetched_persona.description == persona.description
                    and fetched_persona.num_chunks == persona.num_chunks
                    and fetched_persona.llm_relevance_filter
                    == persona.llm_relevance_filter
                    and fetched_persona.is_public == persona.is_public
                    and fetched_persona.llm_filter_extraction
                    == persona.llm_filter_extraction
                    and fetched_persona.llm_model_provider_override
                    == persona.llm_model_provider_override
                    and fetched_persona.llm_model_version_override
                    == persona.llm_model_version_override
                    and set([prompt.id for prompt in fetched_persona.prompts])
                    == set(persona.prompt_ids)
                    and set(
                        [
                            document_set.id
                            for document_set in fetched_persona.document_sets
                        ]
                    )
                    == set(persona.document_set_ids)
                    and set([tool.id for tool in fetched_persona.tools])
                    == set(persona.tool_ids)
                    and set(user.email for user in fetched_persona.users)
                    == set(persona.users)
                    and set(fetched_persona.groups) == set(persona.groups)
                    and {label.id for label in fetched_persona.labels}
                    == set(persona.label_ids)
                )
        return False

    @staticmethod
    def delete(
        persona: DATestPersona,
        user_performing_action: DATestUser | None = None,
    ) -> bool:
        response = requests.delete(
            f"{API_SERVER_URL}/persona/{persona.id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        return response.ok


class PersonaLabelManager:
    @staticmethod
    def create(
        label: DATestPersonaLabel,
        user_performing_action: DATestUser | None = None,
    ) -> DATestPersonaLabel:
        response = requests.post(
            f"{API_SERVER_URL}/persona/labels",
            json={
                "name": label.name,
            },
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        response_data = response.json()
        label.id = response_data["id"]
        return label

    @staticmethod
    def get_all(
        user_performing_action: DATestUser | None = None,
    ) -> list[DATestPersonaLabel]:
        response = requests.get(
            f"{API_SERVER_URL}/persona/labels",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return [DATestPersonaLabel(**label) for label in response.json()]

    @staticmethod
    def update(
        label: DATestPersonaLabel,
        user_performing_action: DATestUser | None = None,
    ) -> DATestPersonaLabel:
        response = requests.patch(
            f"{API_SERVER_URL}/admin/persona/label/{label.id}",
            json={
                "label_name": label.name,
            },
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return label

    @staticmethod
    def delete(
        label: DATestPersonaLabel,
        user_performing_action: DATestUser | None = None,
    ) -> bool:
        response = requests.delete(
            f"{API_SERVER_URL}/admin/persona/label/{label.id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        return response.ok

    @staticmethod
    def verify(
        label: DATestPersonaLabel,
        user_performing_action: DATestUser | None = None,
    ) -> bool:
        all_labels = PersonaLabelManager.get_all(user_performing_action)
        for fetched_label in all_labels:
            if fetched_label.id == label.id:
                return fetched_label.name == label.name
        return False
