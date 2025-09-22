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
        num_chunks: float = 5,
        llm_relevance_filter: bool = True,
        is_public: bool = True,
        llm_filter_extraction: bool = True,
        recency_bias: RecencyBiasSetting = RecencyBiasSetting.AUTO,
        datetime_aware: bool = False,
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
            num_chunks=num_chunks,
            llm_relevance_filter=llm_relevance_filter,
            is_public=is_public,
            llm_filter_extraction=llm_filter_extraction,
            recency_bias=recency_bias,
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
            system_prompt=system_prompt,
            task_prompt=task_prompt,
            datetime_aware=datetime_aware,
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
        num_chunks: float | None = None,
        llm_relevance_filter: bool | None = None,
        is_public: bool | None = None,
        llm_filter_extraction: bool | None = None,
        recency_bias: RecencyBiasSetting | None = None,
        datetime_aware: bool = False,
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
            num_chunks=num_chunks or persona.num_chunks,
            llm_relevance_filter=llm_relevance_filter or persona.llm_relevance_filter,
            is_public=persona.is_public if is_public is None else is_public,
            llm_filter_extraction=(
                llm_filter_extraction or persona.llm_filter_extraction
            ),
            recency_bias=recency_bias or persona.recency_bias,
            document_set_ids=document_set_ids or persona.document_set_ids,
            tool_ids=tool_ids or persona.tool_ids,
            llm_model_provider_override=(
                llm_model_provider_override or persona.llm_model_provider_override
            ),
            llm_model_version_override=(
                llm_model_version_override or persona.llm_model_version_override
            ),
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
            system_prompt=system_prompt,
            task_prompt=task_prompt,
            datetime_aware=datetime_aware,
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
                mismatches: list[tuple[str, object, object]] = []

                if fetched_persona.name != persona.name:
                    mismatches.append(("name", persona.name, fetched_persona.name))
                if fetched_persona.description != persona.description:
                    mismatches.append(
                        (
                            "description",
                            persona.description,
                            fetched_persona.description,
                        )
                    )
                if fetched_persona.num_chunks != persona.num_chunks:
                    mismatches.append(
                        ("num_chunks", persona.num_chunks, fetched_persona.num_chunks)
                    )
                if fetched_persona.llm_relevance_filter != persona.llm_relevance_filter:
                    mismatches.append(
                        (
                            "llm_relevance_filter",
                            persona.llm_relevance_filter,
                            fetched_persona.llm_relevance_filter,
                        )
                    )
                if fetched_persona.is_public != persona.is_public:
                    mismatches.append(
                        ("is_public", persona.is_public, fetched_persona.is_public)
                    )
                if (
                    fetched_persona.llm_filter_extraction
                    != persona.llm_filter_extraction
                ):
                    mismatches.append(
                        (
                            "llm_filter_extraction",
                            persona.llm_filter_extraction,
                            fetched_persona.llm_filter_extraction,
                        )
                    )
                if (
                    fetched_persona.llm_model_provider_override
                    != persona.llm_model_provider_override
                ):
                    mismatches.append(
                        (
                            "llm_model_provider_override",
                            persona.llm_model_provider_override,
                            fetched_persona.llm_model_provider_override,
                        )
                    )
                if (
                    fetched_persona.llm_model_version_override
                    != persona.llm_model_version_override
                ):
                    mismatches.append(
                        (
                            "llm_model_version_override",
                            persona.llm_model_version_override,
                            fetched_persona.llm_model_version_override,
                        )
                    )
                if fetched_persona.system_prompt != persona.system_prompt:
                    mismatches.append(
                        (
                            "system_prompt",
                            persona.system_prompt,
                            fetched_persona.system_prompt,
                        )
                    )
                if fetched_persona.task_prompt != persona.task_prompt:
                    mismatches.append(
                        (
                            "task_prompt",
                            persona.task_prompt,
                            fetched_persona.task_prompt,
                        )
                    )
                if fetched_persona.datetime_aware != persona.datetime_aware:
                    mismatches.append(
                        (
                            "datetime_aware",
                            persona.datetime_aware,
                            fetched_persona.datetime_aware,
                        )
                    )

                fetched_document_set_ids = {
                    document_set.id for document_set in fetched_persona.document_sets
                }
                expected_document_set_ids = set(persona.document_set_ids)
                if fetched_document_set_ids != expected_document_set_ids:
                    mismatches.append(
                        (
                            "document_set_ids",
                            sorted(expected_document_set_ids),
                            sorted(fetched_document_set_ids),
                        )
                    )

                fetched_tool_ids = {tool.id for tool in fetched_persona.tools}
                expected_tool_ids = set(persona.tool_ids)
                if fetched_tool_ids != expected_tool_ids:
                    mismatches.append(
                        (
                            "tool_ids",
                            sorted(expected_tool_ids),
                            sorted(fetched_tool_ids),
                        )
                    )

                fetched_user_emails = {user.email for user in fetched_persona.users}
                expected_user_emails = set(persona.users)
                if fetched_user_emails != expected_user_emails:
                    mismatches.append(
                        (
                            "users",
                            sorted(expected_user_emails),
                            sorted(fetched_user_emails),
                        )
                    )

                fetched_group_ids = set(fetched_persona.groups)
                expected_group_ids = set(persona.groups)
                if fetched_group_ids != expected_group_ids:
                    mismatches.append(
                        (
                            "groups",
                            sorted(expected_group_ids),
                            sorted(fetched_group_ids),
                        )
                    )

                fetched_label_ids = {label.id for label in fetched_persona.labels}
                expected_label_ids = set(persona.label_ids)
                if fetched_label_ids != expected_label_ids:
                    mismatches.append(
                        (
                            "label_ids",
                            sorted(expected_label_ids),
                            sorted(fetched_label_ids),
                        )
                    )

                if mismatches:
                    print(
                        f"Persona verification failed for id={persona.id}. Fields mismatched:"
                    )
                    for field_name, expected_value, actual_value in mismatches:
                        print(
                            f" - {field_name}: expected {expected_value!r}, got {actual_value!r}"
                        )
                    return False
                return True
        print(
            f"Persona verification failed: persona with id={persona.id} not found in fetched results."
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
