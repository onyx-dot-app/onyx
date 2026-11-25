"""
This should act as the main point of reference for testing that default model
logic is consisten.

 -
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import LLMModelFlowType, ModelRole
from onyx.db.llm import (
    fetch_existing_llm_provider,
    fetch_role_model,
    remove_llm_provider,
    set_role_model,
    update_default_vision_provider,
    upsert_llm_provider,
)
from onyx.db.models import ModelConfiguration
from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    LLMProviderView,
    ModelConfigurationUpsertRequest,
)


def _create_test_provider(
    db_session: Session,
    name: str,
    models: list[ModelConfigurationUpsertRequest] | None = None,
) -> LLMProviderView:
    """Helper to create a test LLM provider with multiple models."""
    if models is None:
        models = [
            ModelConfigurationUpsertRequest(
                name="gpt-6-sol", is_visible=True, supports_image_input=True
            ),
            ModelConfigurationUpsertRequest(
                name="gpt-6-luna", is_visible=True, supports_image_input=False
            ),
        ]
    return upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=name,
            provider=LlmProviderNames.OPENAI,
            api_key="sk-test-key-00000000000000000000000000000000000",
            api_key_changed=True,
            model_configurations=models,
        ),
        db_session=db_session,
    )


def _cleanup_provider(db_session: Session, name: str) -> None:
    """Helper to clean up a test provider by name."""
    provider = fetch_existing_llm_provider(name=name, db_session=db_session)
    if provider:
        remove_llm_provider(db_session, provider.id)


@pytest.fixture
def provider_name(db_session: Session) -> Generator[str, None, None]:
    """Generate a unique provider name for each test, with automatic cleanup."""
    name = f"test-provider-{uuid4().hex[:8]}"
    yield name
    db_session.rollback()
    _cleanup_provider(db_session, name)


class TestDefaultModelProtection:
    """Tests that the default model cannot be removed or hidden."""

    def test_cannot_remove_default_text_model(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Removing the default text model from a provider should raise ValueError."""
        provider = _create_test_provider(db_session, provider_name)
        set_role_model(
            db_session=db_session,
            role=ModelRole.CHAT,
            provider_id=provider.id,
            model_name="gpt-6-sol",
        )

        # Try to update the provider without the default model
        with pytest.raises(ValueError, match="Cannot remove the default model"):
            upsert_llm_provider(
                LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key="sk-test-key-00000000000000000000000000000000000",
                    api_key_changed=True,
                    model_configurations=[
                        ModelConfigurationUpsertRequest(
                            name="gpt-6-luna", is_visible=True
                        ),
                    ],
                ),
                db_session=db_session,
            )

    def test_cannot_hide_default_text_model(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Setting is_visible=False on the default text model should raise ValueError."""
        provider = _create_test_provider(db_session, provider_name)
        set_role_model(
            db_session=db_session,
            role=ModelRole.CHAT,
            provider_id=provider.id,
            model_name="gpt-6-sol",
        )

        # Try to hide the default model
        with pytest.raises(ValueError, match="Cannot hide the default model"):
            upsert_llm_provider(
                LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key="sk-test-key-00000000000000000000000000000000000",
                    api_key_changed=True,
                    model_configurations=[
                        ModelConfigurationUpsertRequest(
                            name="gpt-6-sol", is_visible=False
                        ),
                        ModelConfigurationUpsertRequest(
                            name="gpt-6-luna", is_visible=True
                        ),
                    ],
                ),
                db_session=db_session,
            )

    def test_cannot_remove_default_vision_model(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Removing the default vision model from a provider should raise ValueError."""
        provider = _create_test_provider(db_session, provider_name)
        # Set gpt-6-sol as both the text and vision default
        set_role_model(
            db_session=db_session,
            role=ModelRole.CHAT,
            provider_id=provider.id,
            model_name="gpt-6-sol",
        )
        update_default_vision_provider(provider.id, "gpt-6-sol", db_session)

        # Try to remove the default vision model
        with pytest.raises(ValueError, match="Cannot remove the default model"):
            upsert_llm_provider(
                LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key="sk-test-key-00000000000000000000000000000000000",
                    api_key_changed=True,
                    model_configurations=[
                        ModelConfigurationUpsertRequest(
                            name="gpt-6-luna", is_visible=True
                        ),
                    ],
                ),
                db_session=db_session,
            )

    def test_can_remove_non_default_model(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Removing a non-default model should succeed."""
        provider = _create_test_provider(db_session, provider_name)
        set_role_model(
            db_session=db_session,
            role=ModelRole.CHAT,
            provider_id=provider.id,
            model_name="gpt-6-sol",
        )

        # Remove gpt-6-luna (not default) — should succeed
        updated = upsert_llm_provider(
            LLMProviderUpsertRequest(
                id=provider.id,
                name=provider_name,
                provider=LlmProviderNames.OPENAI,
                api_key="sk-test-key-00000000000000000000000000000000000",
                api_key_changed=True,
                model_configurations=[
                    ModelConfigurationUpsertRequest(
                        name="gpt-6-sol", is_visible=True, supports_image_input=True
                    ),
                ],
            ),
            db_session=db_session,
        )

        model_names = {mc.name for mc in updated.model_configurations}
        assert "gpt-6-sol" in model_names
        assert "gpt-6-luna" not in model_names

    def test_can_hide_non_default_model(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Hiding a non-default model should succeed."""
        provider = _create_test_provider(db_session, provider_name)
        set_role_model(
            db_session=db_session,
            role=ModelRole.CHAT,
            provider_id=provider.id,
            model_name="gpt-6-sol",
        )

        # Hide gpt-6-luna (not default) — should succeed
        updated = upsert_llm_provider(
            LLMProviderUpsertRequest(
                id=provider.id,
                name=provider_name,
                provider=LlmProviderNames.OPENAI,
                api_key="sk-test-key-00000000000000000000000000000000000",
                api_key_changed=True,
                model_configurations=[
                    ModelConfigurationUpsertRequest(
                        name="gpt-6-sol", is_visible=True, supports_image_input=True
                    ),
                    ModelConfigurationUpsertRequest(
                        name="gpt-6-luna", is_visible=False
                    ),
                ],
            ),
            db_session=db_session,
        )

        model_visibility = {
            mc.name: mc.is_visible for mc in updated.model_configurations
        }
        assert model_visibility["gpt-6-sol"] is True
        assert model_visibility["gpt-6-luna"] is False


class TestPointerFlowDefaultsSurviveAProviderUpdate:
    """The CHAT_NAMING and CRAFT roles are set by their own endpoints and
    implied by no supports_* field. An ordinary provider edit must not clear them.
    """

    def _update_provider(
        self, db_session: Session, provider_id: int, name: str
    ) -> None:
        """An ordinary edit that names no role, as the admin UI sends."""
        upsert_llm_provider(
            LLMProviderUpsertRequest(
                id=provider_id,
                name=name,
                provider=LlmProviderNames.OPENAI,
                api_key="sk-test-key-00000000000000000000000000000000000",
                api_key_changed=True,
                model_configurations=[
                    ModelConfigurationUpsertRequest(
                        name="gpt-6-sol", is_visible=True, supports_image_input=True
                    ),
                    ModelConfigurationUpsertRequest(
                        name="gpt-6-luna", is_visible=True, supports_image_input=False
                    ),
                ],
            ),
            db_session=db_session,
        )

    def test_craft_default_survives(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        provider = _create_test_provider(db_session, provider_name)
        set_role_model(
            db_session=db_session,
            role=ModelRole.CRAFT,
            provider_id=provider.id,
            model_name="gpt-6-luna",
        )
        assert fetch_role_model(db_session, ModelRole.CRAFT) is not None

        self._update_provider(db_session, provider.id, provider_name)

        default_craft = fetch_role_model(db_session, ModelRole.CRAFT)
        assert default_craft is not None
        assert default_craft.name == "gpt-6-luna"

    def _hide_mini(self, db_session: Session, provider_id: int, name: str) -> None:
        upsert_llm_provider(
            LLMProviderUpsertRequest(
                id=provider_id,
                name=name,
                provider=LlmProviderNames.OPENAI,
                api_key="sk-test-key-00000000000000000000000000000000000",
                api_key_changed=True,
                model_configurations=[
                    ModelConfigurationUpsertRequest(
                        name="gpt-6-sol", is_visible=True, supports_image_input=True
                    ),
                    ModelConfigurationUpsertRequest(
                        name="gpt-6-luna", is_visible=False, supports_image_input=False
                    ),
                ],
            ),
            db_session=db_session,
        )

    def test_hiding_the_craft_default_is_refused(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Keeping the row means the model under it must stay visible. Neither
        resolver checks is_visible, so a hidden default would still be used."""
        provider = _create_test_provider(db_session, provider_name)
        set_role_model(
            db_session=db_session,
            role=ModelRole.CRAFT,
            provider_id=provider.id,
            model_name="gpt-6-luna",
        )

        with pytest.raises(ValueError, match="Cannot hide the default model"):
            self._hide_mini(db_session, provider.id, provider_name)

    def test_chat_naming_default_survives(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        provider = _create_test_provider(db_session, provider_name)
        set_role_model(
            db_session=db_session,
            role=ModelRole.CHAT_NAMING,
            provider_id=provider.id,
            model_name="gpt-6-luna",
        )
        assert fetch_role_model(db_session, ModelRole.CHAT_NAMING) is not None

        self._update_provider(db_session, provider.id, provider_name)

        default_naming = fetch_role_model(db_session, ModelRole.CHAT_NAMING)
        assert default_naming is not None
        assert default_naming.name == "gpt-6-luna"


class TestEveryFlowDefaultIsGuarded:
    """The guard covers every flow a model is the default for, and refuses only
    the visible-to-hidden transition."""

    def _upsert(
        self,
        db_session: Session,
        provider_id: int,
        name: str,
        models: list[ModelConfigurationUpsertRequest],
    ) -> LLMProviderView:
        return upsert_llm_provider(
            LLMProviderUpsertRequest(
                id=provider_id,
                name=name,
                provider=LlmProviderNames.OPENAI,
                api_key="sk-test-key-00000000000000000000000000000000000",
                api_key_changed=True,
                model_configurations=models,
            ),
            db_session=db_session,
        )

    def test_hiding_a_vision_only_default_is_refused(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """The existing vision test puts both defaults on one model, so the chat
        check alone caught it. Here only the vision default is at stake."""
        provider = _create_test_provider(db_session, provider_name)
        set_role_model(
            db_session=db_session,
            role=ModelRole.CHAT,
            provider_id=provider.id,
            model_name="gpt-6-luna",
        )
        update_default_vision_provider(provider.id, "gpt-6-sol", db_session)

        with pytest.raises(ValueError, match="default for: image_processing"):
            self._upsert(
                db_session,
                provider.id,
                provider_name,
                [
                    ModelConfigurationUpsertRequest(
                        name="gpt-6-sol", is_visible=False, supports_image_input=True
                    ),
                    ModelConfigurationUpsertRequest(
                        name="gpt-6-luna", is_visible=True, supports_image_input=False
                    ),
                ],
            )

    def test_removing_the_craft_default_is_refused(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        provider = _create_test_provider(db_session, provider_name)
        set_role_model(
            db_session=db_session,
            role=ModelRole.CRAFT,
            provider_id=provider.id,
            model_name="gpt-6-luna",
        )

        with pytest.raises(ValueError, match="Cannot remove the default model"):
            self._upsert(
                db_session,
                provider.id,
                provider_name,
                [
                    ModelConfigurationUpsertRequest(
                        name="gpt-6-sol", is_visible=True, supports_image_input=True
                    )
                ],
            )

    def test_already_hidden_default_does_not_block_an_edit(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """An admin can hide a model that holds the vision default, so a vision
        default can already sit on a hidden model. The form then re-sends that stored visibility, and an
        unrelated edit — an API key rotation — must not be refused for it."""
        provider = _create_test_provider(db_session, provider_name)
        set_role_model(
            db_session=db_session,
            role=ModelRole.CHAT,
            provider_id=provider.id,
            model_name="gpt-6-luna",
        )
        update_default_vision_provider(provider.id, "gpt-6-sol", db_session)

        hidden = db_session.scalar(
            select(ModelConfiguration).where(
                ModelConfiguration.llm_provider_id == provider.id,
                ModelConfiguration.name == "gpt-6-sol",
            )
        )
        assert hidden is not None
        hidden.is_visible = False
        db_session.commit()

        self._upsert(
            db_session,
            provider.id,
            provider_name,
            [
                ModelConfigurationUpsertRequest(
                    name="gpt-6-sol", is_visible=False, supports_image_input=True
                ),
                ModelConfigurationUpsertRequest(
                    name="gpt-6-luna", is_visible=True, supports_image_input=False
                ),
            ],
        )

        default_vision = fetch_role_model(db_session, ModelRole.IMAGE_PROCESSING)
        assert default_vision is not None
        assert default_vision.name == "gpt-6-sol"

    def test_capability_change_still_removes_the_vision_flow(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Dropping a capability the held role does not need must still
        reconcile its flow away."""
        provider = _create_test_provider(db_session, provider_name)
        set_role_model(
            db_session=db_session,
            role=ModelRole.CRAFT,
            provider_id=provider.id,
            model_name="gpt-6-sol",
        )

        self._upsert(
            db_session,
            provider.id,
            provider_name,
            [
                ModelConfigurationUpsertRequest(
                    name="gpt-6-sol", is_visible=True, supports_image_input=False
                ),
                ModelConfigurationUpsertRequest(
                    name="gpt-6-luna", is_visible=True, supports_image_input=False
                ),
            ],
        )

        model_config = db_session.scalar(
            select(ModelConfiguration).where(
                ModelConfiguration.llm_provider_id == provider.id,
                ModelConfiguration.name == "gpt-6-sol",
            )
        )
        assert model_config is not None
        db_session.refresh(model_config)
        flows = set(model_config.llm_model_flow_types)
        assert LLMModelFlowType.VISION not in flows

        default_craft = fetch_role_model(db_session, ModelRole.CRAFT)
        assert default_craft is not None
        assert default_craft.name == "gpt-6-sol"


class TestCapabilityChangesCannotEraseADefault:
    """A role needs capabilities, so dropping one its model needs would leave
    the role on a model that cannot service it."""

    def test_cannot_disable_image_input_on_the_vision_default(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        provider = _create_test_provider(db_session, provider_name)
        update_default_vision_provider(provider.id, "gpt-6-sol", db_session)

        with pytest.raises(
            ValueError,
            match=r"Cannot remove the capabilities that the image_processing role needs",
        ):
            upsert_llm_provider(
                LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key="sk-test-key-00000000000000000000000000000000000",
                    api_key_changed=True,
                    model_configurations=[
                        ModelConfigurationUpsertRequest(
                            name="gpt-6-sol",
                            is_visible=True,
                            supports_image_input=False,
                        ),
                        ModelConfigurationUpsertRequest(
                            name="gpt-6-luna", is_visible=True
                        ),
                    ],
                ),
                db_session=db_session,
            )

        assert fetch_role_model(db_session, ModelRole.IMAGE_PROCESSING) is not None

    def test_omitting_image_support_keeps_the_stored_capability(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """supports_image_input is optional. An omitted one used to read as false
        and silently drop the vision flow the image processing role needs."""
        provider = _create_test_provider(db_session, provider_name)
        update_default_vision_provider(provider.id, "gpt-6-sol", db_session)

        upsert_llm_provider(
            LLMProviderUpsertRequest(
                id=provider.id,
                name=provider_name,
                provider=LlmProviderNames.OPENAI,
                api_key="sk-test-key-00000000000000000000000000000000000",
                api_key_changed=True,
                model_configurations=[
                    # no supports_image_input, as a partial client would send
                    ModelConfigurationUpsertRequest(name="gpt-6-sol", is_visible=True),
                    ModelConfigurationUpsertRequest(name="gpt-6-luna", is_visible=True),
                ],
            ),
            db_session=db_session,
        )

        default_vision = fetch_role_model(db_session, ModelRole.IMAGE_PROCESSING)
        assert default_vision is not None
        assert default_vision.name == "gpt-6-sol"

    def test_disabling_vision_is_caught_when_one_model_holds_several_defaults(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """The chat default is commonly the image processing default too. Every
        role the model holds must be checked, not only the first found."""
        provider = _create_test_provider(db_session, provider_name)
        set_role_model(
            db_session=db_session,
            role=ModelRole.CHAT,
            provider_id=provider.id,
            model_name="gpt-6-sol",
        )
        update_default_vision_provider(provider.id, "gpt-6-sol", db_session)

        with pytest.raises(
            ValueError,
            match=r"Cannot remove the capabilities that the image_processing role needs",
        ):
            upsert_llm_provider(
                LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key="sk-test-key-00000000000000000000000000000000000",
                    api_key_changed=True,
                    model_configurations=[
                        ModelConfigurationUpsertRequest(
                            name="gpt-6-sol",
                            is_visible=True,
                            supports_image_input=False,
                        ),
                        ModelConfigurationUpsertRequest(
                            name="gpt-6-luna", is_visible=True
                        ),
                    ],
                ),
                db_session=db_session,
            )
