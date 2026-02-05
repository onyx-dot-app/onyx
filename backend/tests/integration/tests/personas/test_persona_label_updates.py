from uuid import uuid4

import requests

from onyx.server.features.persona.models import PersonaUpsertRequest
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.persona import PersonaLabelManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestPersonaLabel
from tests.integration.common_utils.test_models import DATestUser


def test_update_persona_with_null_label_ids_preserves_labels(
    reset: None, admin_user: DATestUser
) -> None:
    persona_label = PersonaLabelManager.create(
        label=DATestPersonaLabel(name=f"Test label {uuid4()}"),
        user_performing_action=admin_user,
    )
    assert persona_label.id is not None
    persona = PersonaManager.create(
        label_ids=[persona_label.id],
        user_performing_action=admin_user,
    )

    updated_description = f"{persona.description}-updated"
    update_request = PersonaUpsertRequest(
        name=persona.name,
        description=updated_description,
        system_prompt=persona.system_prompt or "",
        task_prompt=persona.task_prompt or "",
        datetime_aware=persona.datetime_aware,
        document_set_ids=persona.document_set_ids,
        num_chunks=persona.num_chunks,
        is_public=persona.is_public,
        recency_bias=persona.recency_bias,
        llm_filter_extraction=persona.llm_filter_extraction,
        llm_relevance_filter=persona.llm_relevance_filter,
        llm_model_provider_override=persona.llm_model_provider_override,
        llm_model_version_override=persona.llm_model_version_override,
        tool_ids=persona.tool_ids,
        users=[],
        groups=[],
        label_ids=None,
    )

    response = requests.patch(
        f"{API_SERVER_URL}/persona/{persona.id}",
        json=update_request.model_dump(mode="json", exclude_none=False),
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    response.raise_for_status()

    fetched = requests.get(
        f"{API_SERVER_URL}/persona/{persona.id}",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    fetched.raise_for_status()
    fetched_persona = fetched.json()

    assert fetched_persona["description"] == updated_description
    fetched_label_ids = {label["id"] for label in fetched_persona["labels"]}
    assert persona_label.id in fetched_label_ids
