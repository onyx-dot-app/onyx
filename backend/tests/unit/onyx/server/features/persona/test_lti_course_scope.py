"""Course tutor scope is enforced by the persona API, including non-UI callers."""

from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.persona import api
from onyx.server.features.persona.models import PersonaUpsertRequest


def request(**changes: object) -> PersonaUpsertRequest:
    fields = {
        "name": "Tutor",
        "description": "",
        "document_set_ids": [],
        "is_public": True,
        "tool_ids": [1],
        "system_prompt": "",
        "task_prompt": "",
        "datetime_aware": False,
        "label_ids": [1, 2],
        "lti_context_id": "course-1",
    }
    fields.update(changes)
    return PersonaUpsertRequest.model_validate(fields)


@pytest.fixture
def tutor_api() -> Generator[MagicMock, None, None]:
    tutor = MagicMock()
    tutor.labels = [
        MagicMock(id=1, name="Virtual Tutor"),
        MagicMock(id=2, name="course-1"),
    ]
    # MagicMock reserves name, so assign it explicitly.
    tutor.labels[0].name = "Virtual Tutor"
    tutor.labels[1].name = "course-1"
    with (
        patch.object(
            api, "fetch_persona_by_id_for_user", return_value=tutor, create=True
        ),
        patch.object(
            api,
            "get_persona_label_names_by_ids",
            return_value={"Virtual Tutor", "course-1"},
            create=True,
        ),
        patch.object(
            api,
            "filter_orphaned_persona_hierarchy_node_ids",
            side_effect=lambda **kw: kw["hierarchy_node_ids"],
        ),
        patch.object(api, "validate_lti_course_knowledge_selection") as validate,
        patch.object(api, "create_update_persona") as save,
        patch.object(api, "_validate_user_knowledge_enabled"),
        patch.object(api, "_validate_vector_db_knowledge"),
    ):
        context = MagicMock()
        context.validate = validate
        context.save = save
        yield context


def test_existing_tutor_requires_course_scope_without_client_context(
    tutor_api: MagicMock,
) -> None:
    api.update_persona(42, request(lti_context_id=None), MagicMock(), MagicMock())
    assert tutor_api.validate.call_args.kwargs["course_id"] == "course-1"
    assert tutor_api.save.call_args.kwargs["disable_search_if_unscoped"] is True
    assert tutor_api.save.call_args.kwargs["create_persona_request"].user_file_ids == []


@pytest.mark.parametrize(
    "field,value", [("document_set_ids", [4]), ("user_file_ids", [str(uuid4())])]
)
def test_tutor_rejects_unsupported_attachments(
    tutor_api: MagicMock, field: str, value: object
) -> None:
    with pytest.raises(OnyxError):
        api.update_persona(42, request(**{field: value}), MagicMock(), MagicMock())
    tutor_api.save.assert_not_called()


def test_tutor_rejects_a_different_client_course(tutor_api: MagicMock) -> None:
    with pytest.raises(OnyxError):
        api.update_persona(
            42, request(lti_context_id="course-2"), MagicMock(), MagicMock()
        )
    tutor_api.save.assert_not_called()


def test_tutor_rejects_removing_course_labels(tutor_api: MagicMock) -> None:
    with patch.object(api, "get_persona_label_names_by_ids", return_value=set()):
        with pytest.raises(OnyxError):
            api.update_persona(42, request(label_ids=[]), MagicMock(), MagicMock())
    tutor_api.save.assert_not_called()
