"""Building an LLM uses the chosen model's saved configuration, and neither an
LLM build nor a provider listing runs more queries as a provider gains models."""

from collections.abc import Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import (
    fetch_all_accessible_llm_providers,
    fetch_default_model,
    remove_llm_provider,
    update_default_model,
    upsert_llm_provider,
)
from onyx.db.models import Persona
from onyx.llm.factory import get_default_llm, get_llm_for_persona
from onyx.llm.interfaces import LLM
from onyx.llm.override_models import LLMOverride
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)
from tests.external_dependency_unit.conftest import MakeTestUser

_CHOSEN = "gpt-factory-chosen"
_CHOSEN_MAX_INPUT_TOKENS = 123_456
# Provider views hide this dated variant because "gpt-factory" exists.
_DATED = "gpt-factory-2024-07-18"
_DATED_MAX_INPUT_TOKENS = 234_567


def _query_counts(
    db_session: Session,
    executed_sql: list[str],
    make_test_user: MakeTestUser,
    filler_model_count: int,
) -> dict[str, int]:
    user = make_test_user("llm-factory-queries")
    previous = fetch_default_model(db_session, LLMModelFlowType.CHAT)
    previous_default = (
        None if previous is None else (previous.llm_provider_id, previous.name)
    )
    provider = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=f"test-factory-queries-{uuid4().hex}",
            provider="openai",
            api_key="test",
            model_configurations=[
                ModelConfigurationUpsertRequest(name="gpt-factory", is_visible=True),
                ModelConfigurationUpsertRequest(
                    name=_CHOSEN,
                    is_visible=True,
                    max_input_tokens=_CHOSEN_MAX_INPUT_TOKENS,
                ),
                ModelConfigurationUpsertRequest(
                    name=_DATED,
                    is_visible=True,
                    max_input_tokens=_DATED_MAX_INPUT_TOKENS,
                ),
                *(
                    ModelConfigurationUpsertRequest(
                        name=f"gpt-factory-filler-{index}", is_visible=True
                    )
                    for index in range(filler_model_count)
                ),
            ],
        ),
        db_session,
    )
    try:
        update_default_model(
            db_session, provider.id, "gpt-factory", LLMModelFlowType.CHAT
        )
        ids = {mc.name: mc.id for mc in provider.model_configurations}
        builds: dict[str, tuple[Callable[[], object], int | None]] = {
            "default": (get_default_llm, None),
            "persona_default": (
                lambda: get_llm_for_persona(
                    Persona(id=-1, default_model_configuration_id=ids[_CHOSEN]), user
                ),
                _CHOSEN_MAX_INPUT_TOKENS,
            ),
            "override_by_name": (
                lambda: get_llm_for_persona(
                    Persona(id=-1, default_model_configuration_id=None),
                    user,
                    LLMOverride(model_provider=provider.name, model_version=_CHOSEN),
                ),
                _CHOSEN_MAX_INPUT_TOKENS,
            ),
            "override_by_id": (
                lambda: get_llm_for_persona(
                    Persona(id=-1, default_model_configuration_id=None),
                    user,
                    LLMOverride(model_configuration_id=ids[_CHOSEN]),
                ),
                _CHOSEN_MAX_INPUT_TOKENS,
            ),
            "dated_override_by_name": (
                lambda: get_llm_for_persona(
                    Persona(id=-1, default_model_configuration_id=None),
                    user,
                    LLMOverride(model_provider=provider.name, model_version=_DATED),
                ),
                _DATED_MAX_INPUT_TOKENS,
            ),
            "accessible_provider_catalog": (
                lambda: fetch_all_accessible_llm_providers(db_session, user),
                None,
            ),
        }
        counts: dict[str, int] = {}
        for label, (build, expected_max_input_tokens) in builds.items():
            db_session.expire_all()
            executed_sql.clear()
            built = build()
            counts[label] = len(executed_sql)
            if expected_max_input_tokens is not None:
                assert isinstance(built, LLM)
                assert built.config.max_input_tokens == expected_max_input_tokens, label
        return counts
    finally:
        db_session.rollback()
        if previous_default is not None:
            update_default_model(db_session, *previous_default, LLMModelFlowType.CHAT)
        remove_llm_provider(db_session, provider.id)


def test_llm_build_uses_chosen_config_and_query_count_is_flat(
    db_session: Session,
    executed_sql: list[str],
    make_test_user: MakeTestUser,
) -> None:
    small = _query_counts(
        db_session, executed_sql, make_test_user, filler_model_count=0
    )
    large = _query_counts(
        db_session, executed_sql, make_test_user, filler_model_count=40
    )

    assert all(count > 0 for count in small.values())
    assert large == small
