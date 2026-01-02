from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.db.models import CloudEmbeddingProvider as CloudEmbeddingProviderModel
from onyx.db.models import DocumentSet
from onyx.db.models import ImageGenerationConfig
from onyx.db.models import LLMProvider as LLMProviderModel
from onyx.db.models import LLMProvider__Persona
from onyx.db.models import LLMProvider__UserGroup
from onyx.db.models import ModelConfiguration
from onyx.db.models import Persona
from onyx.db.models import SearchSettings
from onyx.db.models import Tool as ToolModel
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.llm.utils import model_supports_image_input
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations
from onyx.server.manage.embedding.models import CloudEmbeddingProvider
from onyx.server.manage.embedding.models import CloudEmbeddingProviderCreationRequest
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import LLMProviderView
from shared_configs.enums import EmbeddingProvider


def update_group_llm_provider_relationships__no_commit(
    llm_provider_id: int,
    group_ids: list[int] | None,
    db_session: Session,
) -> None:
    # Delete existing relationships
    db_session.query(LLMProvider__UserGroup).filter(
        LLMProvider__UserGroup.llm_provider_id == llm_provider_id
    ).delete(synchronize_session="fetch")

    # Add new relationships from given group_ids
    if group_ids:
        new_relationships = [
            LLMProvider__UserGroup(
                llm_provider_id=llm_provider_id,
                user_group_id=group_id,
            )
            for group_id in group_ids
        ]
        db_session.add_all(new_relationships)


def update_llm_provider_persona_relationships__no_commit(
    db_session: Session,
    llm_provider_id: int,
    persona_ids: list[int] | None,
) -> None:
    """Replace the persona restrictions for a provider within an open transaction."""
    db_session.execute(
        delete(LLMProvider__Persona).where(
            LLMProvider__Persona.llm_provider_id == llm_provider_id
        )
    )

    if persona_ids:
        db_session.add_all(
            LLMProvider__Persona(
                llm_provider_id=llm_provider_id,
                persona_id=persona_id,
            )
            for persona_id in persona_ids
        )


def fetch_user_group_ids(db_session: Session, user: User | None) -> set[int]:
    """Fetch the set of user group IDs for a given user.

    Args:
        db_session: Database session
        user: User to fetch groups for, or None for anonymous users

    Returns:
        Set of user group IDs. Empty set if user is None.
    """
    if not user:
        return set()

    return set(
        db_session.scalars(
            select(User__UserGroup.user_group_id).where(
                User__UserGroup.user_id == user.id
            )
        ).all()
    )


def can_user_access_llm_provider(
    provider: LLMProviderModel,
    user_group_ids: set[int],
    persona: Persona | None,
    is_admin: bool = False,
) -> bool:
    """Check if a user may use an LLM provider.

    Args:
        provider: The LLM provider to check access for
        user_group_ids: Set of user group IDs the user belongs to
        persona: The persona being used (if any)
        is_admin: If True, bypass user group restrictions but still respect persona restrictions

    Access logic:
    1. If is_public=True → everyone has access (public override)
    2. If is_public=False:
       - Both groups AND personas set → must satisfy BOTH (AND logic, admins bypass group check)
       - Only groups set → must be in one of the groups (OR across groups, admins bypass)
       - Only personas set → must use one of the personas (OR across personas, applies to admins)
       - Neither set → NOBODY has access unless admin (locked, admin-only)
    """
    # Public override - everyone has access
    if provider.is_public:
        return True

    # Extract IDs once to avoid multiple iterations
    provider_group_ids = (
        {group.id for group in provider.groups} if provider.groups else set()
    )
    provider_persona_ids = (
        {p.id for p in provider.personas} if provider.personas else set()
    )

    has_groups = bool(provider_group_ids)
    has_personas = bool(provider_persona_ids)

    # Both groups AND personas set → AND logic (must satisfy both)
    if has_groups and has_personas:
        # Admins bypass group check but still must satisfy persona restrictions
        user_in_group = is_admin or bool(user_group_ids & provider_group_ids)
        persona_allowed = persona.id in provider_persona_ids if persona else False
        return user_in_group and persona_allowed

    # Only groups set → user must be in one of the groups (admins bypass)
    if has_groups:
        return is_admin or bool(user_group_ids & provider_group_ids)

    # Only personas set → persona must be in allowed list (applies to admins too)
    if has_personas:
        return persona.id in provider_persona_ids if persona else False

    # Neither groups nor personas set, and not public → admins can access
    return is_admin


def validate_persona_ids_exist(
    db_session: Session, persona_ids: list[int]
) -> tuple[set[int], list[int]]:
    """Validate that persona IDs exist in the database.

    Returns:
        Tuple of (fetched_persona_ids, missing_personas)
    """
    fetched_persona_ids = set(
        db_session.scalars(select(Persona.id).where(Persona.id.in_(persona_ids))).all()
    )
    missing_personas = sorted(set(persona_ids) - fetched_persona_ids)
    return fetched_persona_ids, missing_personas


def get_personas_using_provider(
    db_session: Session, provider_name: str
) -> list[Persona]:
    """Get all non-deleted personas that use a specific LLM provider."""
    return list(
        db_session.scalars(
            select(Persona).where(
                Persona.llm_model_provider_override == provider_name,
                Persona.deleted == False,  # noqa: E712
            )
        ).all()
    )


def fetch_persona_with_groups(db_session: Session, persona_id: int) -> Persona | None:
    """Fetch a persona with its groups eagerly loaded."""
    return db_session.scalar(
        select(Persona)
        .options(selectinload(Persona.groups))
        .where(Persona.id == persona_id, Persona.deleted == False)  # noqa: E712
    )


def upsert_cloud_embedding_provider(
    db_session: Session, provider: CloudEmbeddingProviderCreationRequest
) -> CloudEmbeddingProvider:
    existing_provider = (
        db_session.query(CloudEmbeddingProviderModel)
        .filter_by(provider_type=provider.provider_type)
        .first()
    )
    if existing_provider:
        for key, value in provider.model_dump().items():
            setattr(existing_provider, key, value)
    else:
        new_provider = CloudEmbeddingProviderModel(**provider.model_dump())

        db_session.add(new_provider)
        existing_provider = new_provider
    db_session.commit()
    db_session.refresh(existing_provider)
    return CloudEmbeddingProvider.from_request(existing_provider)


def upsert_llm_provider(
    llm_provider_upsert_request: LLMProviderUpsertRequest,
    db_session: Session,
) -> LLMProviderView:
    existing_llm_provider = fetch_existing_llm_provider(
        name=llm_provider_upsert_request.name, db_session=db_session
    )

    if not existing_llm_provider:
        existing_llm_provider = LLMProviderModel(name=llm_provider_upsert_request.name)
        db_session.add(existing_llm_provider)

    # Filter out empty strings and None values from custom_config to allow
    # providers like Bedrock to fall back to IAM roles when credentials are not provided
    custom_config = llm_provider_upsert_request.custom_config
    if custom_config:
        custom_config = {
            k: v for k, v in custom_config.items() if v is not None and v.strip() != ""
        }
        # Set to None if the dict is empty after filtering
        custom_config = custom_config if custom_config else None

    existing_llm_provider.provider = llm_provider_upsert_request.provider
    existing_llm_provider.api_key = llm_provider_upsert_request.api_key
    existing_llm_provider.api_base = llm_provider_upsert_request.api_base
    existing_llm_provider.api_version = llm_provider_upsert_request.api_version
    existing_llm_provider.custom_config = custom_config
    existing_llm_provider.default_model_name = (
        llm_provider_upsert_request.default_model_name
    )
    existing_llm_provider.is_public = llm_provider_upsert_request.is_public
    existing_llm_provider.is_auto_mode = llm_provider_upsert_request.is_auto_mode
    existing_llm_provider.deployment_name = llm_provider_upsert_request.deployment_name

    if not existing_llm_provider.id:
        # If its not already in the db, we need to generate an ID by flushing
        db_session.flush()

    # Delete existing model configurations
    db_session.query(ModelConfiguration).filter(
        ModelConfiguration.llm_provider_id == existing_llm_provider.id
    ).delete(synchronize_session="fetch")

    db_session.flush()

    # Import here to avoid circular imports
    from onyx.llm.utils import get_max_input_tokens

    for model_configuration in llm_provider_upsert_request.model_configurations:
        # If max_input_tokens is not provided, look it up from LiteLLM
        max_input_tokens = model_configuration.max_input_tokens
        if max_input_tokens is None:
            max_input_tokens = get_max_input_tokens(
                model_name=model_configuration.name,
                model_provider=llm_provider_upsert_request.provider,
            )

        db_session.execute(
            insert(ModelConfiguration)
            .values(
                llm_provider_id=existing_llm_provider.id,
                name=model_configuration.name,
                is_visible=model_configuration.is_visible,
                max_input_tokens=max_input_tokens,
                supports_image_input=model_configuration.supports_image_input,
                display_name=model_configuration.display_name,
            )
            .on_conflict_do_nothing()
        )

    # Make sure the relationship table stays up to date
    update_group_llm_provider_relationships__no_commit(
        llm_provider_id=existing_llm_provider.id,
        group_ids=llm_provider_upsert_request.groups,
        db_session=db_session,
    )
    update_llm_provider_persona_relationships__no_commit(
        db_session=db_session,
        llm_provider_id=existing_llm_provider.id,
        persona_ids=llm_provider_upsert_request.personas,
    )

    db_session.flush()
    db_session.refresh(existing_llm_provider)

    try:
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        raise ValueError(f"Failed to save LLM provider: {str(e)}") from e

    full_llm_provider = LLMProviderView.from_model(existing_llm_provider)
    return full_llm_provider


def sync_model_configurations(
    db_session: Session,
    provider_name: str,
    models: list[dict],
) -> int:
    """Sync model configurations for a dynamic provider (OpenRouter, Bedrock, Ollama).

    This inserts NEW models from the source API without overwriting existing ones.
    User preferences (is_visible, max_input_tokens) are preserved for existing models.

    Args:
        db_session: Database session
        provider_name: Name of the LLM provider
        models: List of model dicts with keys: name, display_name, max_input_tokens, supports_image_input

    Returns:
        Number of new models added
    """
    provider = fetch_existing_llm_provider(name=provider_name, db_session=db_session)
    if not provider:
        raise ValueError(f"LLM Provider '{provider_name}' not found")

    # Get existing model names to count new additions
    existing_names = {mc.name for mc in provider.model_configurations}

    new_count = 0
    for model in models:
        model_name = model["name"]
        if model_name not in existing_names:
            # Insert new model with is_visible=False (user must explicitly enable)
            db_session.execute(
                insert(ModelConfiguration)
                .values(
                    llm_provider_id=provider.id,
                    name=model_name,
                    is_visible=False,
                    max_input_tokens=model.get("max_input_tokens"),
                    supports_image_input=model.get("supports_image_input", False),
                    display_name=model.get("display_name"),
                )
                .on_conflict_do_nothing()
            )
            new_count += 1

    if new_count > 0:
        db_session.commit()

    return new_count


def fetch_existing_embedding_providers(
    db_session: Session,
) -> list[CloudEmbeddingProviderModel]:
    return list(db_session.scalars(select(CloudEmbeddingProviderModel)).all())


def fetch_existing_doc_sets(
    db_session: Session, doc_ids: list[int]
) -> list[DocumentSet]:
    return list(
        db_session.scalars(select(DocumentSet).where(DocumentSet.id.in_(doc_ids))).all()
    )


def fetch_existing_tools(db_session: Session, tool_ids: list[int]) -> list[ToolModel]:
    return list(
        db_session.scalars(select(ToolModel).where(ToolModel.id.in_(tool_ids))).all()
    )


def fetch_existing_llm_providers(
    db_session: Session,
    only_public: bool = False,
    exclude_image_generation_providers: bool = False,
) -> list[LLMProviderModel]:
    """Fetch all LLM providers with optional filtering.

    Args:
        db_session: Database session
        only_public: If True, only return public providers
        exclude_image_generation_providers: If True, exclude providers that are
            used for image generation configs
    """
    stmt = select(LLMProviderModel).options(
        selectinload(LLMProviderModel.model_configurations),
        selectinload(LLMProviderModel.groups),
        selectinload(LLMProviderModel.personas),
    )

    if exclude_image_generation_providers:
        # Get LLM provider IDs used by ImageGenerationConfig
        image_gen_provider_ids = select(ModelConfiguration.llm_provider_id).join(
            ImageGenerationConfig
        )
        stmt = stmt.where(LLMProviderModel.id.not_in(image_gen_provider_ids))

    providers = list(db_session.scalars(stmt).all())
    if only_public:
        return [provider for provider in providers if provider.is_public]
    return providers


def fetch_existing_llm_provider(
    name: str, db_session: Session
) -> LLMProviderModel | None:
    provider_model = db_session.scalar(
        select(LLMProviderModel)
        .where(LLMProviderModel.name == name)
        .options(
            selectinload(LLMProviderModel.model_configurations),
            selectinload(LLMProviderModel.groups),
            selectinload(LLMProviderModel.personas),
        )
    )

    return provider_model


def fetch_embedding_provider(
    db_session: Session, provider_type: EmbeddingProvider
) -> CloudEmbeddingProviderModel | None:
    return db_session.scalar(
        select(CloudEmbeddingProviderModel).where(
            CloudEmbeddingProviderModel.provider_type == provider_type
        )
    )


def fetch_default_provider(db_session: Session) -> LLMProviderView | None:
    provider_model = db_session.scalar(
        select(LLMProviderModel)
        .where(LLMProviderModel.is_default_provider == True)  # noqa: E712
        .options(selectinload(LLMProviderModel.model_configurations))
    )
    if not provider_model:
        return None
    return LLMProviderView.from_model(provider_model)


def fetch_default_vision_provider(db_session: Session) -> LLMProviderView | None:
    provider_model = db_session.scalar(
        select(LLMProviderModel)
        .where(LLMProviderModel.is_default_vision_provider == True)  # noqa: E712
        .options(selectinload(LLMProviderModel.model_configurations))
    )
    if not provider_model:
        return None
    return LLMProviderView.from_model(provider_model)


def fetch_llm_provider_view(
    db_session: Session, provider_name: str
) -> LLMProviderView | None:
    provider_model = fetch_existing_llm_provider(
        name=provider_name, db_session=db_session
    )
    if not provider_model:
        return None
    return LLMProviderView.from_model(provider_model)


def remove_embedding_provider(
    db_session: Session, provider_type: EmbeddingProvider
) -> None:
    db_session.execute(
        delete(SearchSettings).where(SearchSettings.provider_type == provider_type)
    )

    # Delete the embedding provider
    db_session.execute(
        delete(CloudEmbeddingProviderModel).where(
            CloudEmbeddingProviderModel.provider_type == provider_type
        )
    )

    db_session.commit()


def remove_llm_provider(db_session: Session, provider_id: int) -> None:
    provider = db_session.get(LLMProviderModel, provider_id)
    if not provider:
        raise ValueError("LLM Provider not found")

    # Clear the provider override from any personas using it
    # This causes them to fall back to the default provider
    personas_using_provider = get_personas_using_provider(db_session, provider.name)
    for persona in personas_using_provider:
        persona.llm_model_provider_override = None

    db_session.execute(
        delete(LLMProvider__UserGroup).where(
            LLMProvider__UserGroup.llm_provider_id == provider_id
        )
    )
    # Remove LLMProvider
    db_session.execute(
        delete(LLMProviderModel).where(LLMProviderModel.id == provider_id)
    )
    db_session.commit()


def remove_llm_provider__no_commit(db_session: Session, provider_id: int) -> None:
    """Remove LLM provider."""
    provider = db_session.get(LLMProviderModel, provider_id)
    if not provider:
        raise ValueError("LLM Provider not found")

    # Clear the provider override from any personas using it
    # This causes them to fall back to the default provider
    personas_using_provider = get_personas_using_provider(db_session, provider.name)
    for persona in personas_using_provider:
        persona.llm_model_provider_override = None

    db_session.execute(
        delete(LLMProvider__UserGroup).where(
            LLMProvider__UserGroup.llm_provider_id == provider_id
        )
    )
    # Remove LLMProvider
    db_session.execute(
        delete(LLMProviderModel).where(LLMProviderModel.id == provider_id)
    )
    db_session.flush()


def update_default_provider(provider_id: int, db_session: Session) -> None:
    new_default = db_session.scalar(
        select(LLMProviderModel).where(LLMProviderModel.id == provider_id)
    )
    if not new_default:
        raise ValueError(f"LLM Provider with id {provider_id} does not exist")

    existing_default = db_session.scalar(
        select(LLMProviderModel).where(
            LLMProviderModel.is_default_provider == True  # noqa: E712
        )
    )
    if existing_default:
        existing_default.is_default_provider = None
        # required to ensure that the below does not cause a unique constraint violation
        db_session.flush()

    new_default.is_default_provider = True
    db_session.commit()


def update_default_vision_provider(
    provider_id: int, vision_model: str | None, db_session: Session
) -> None:
    new_default = db_session.scalar(
        select(LLMProviderModel).where(LLMProviderModel.id == provider_id)
    )
    if not new_default:
        raise ValueError(f"LLM Provider with id {provider_id} does not exist")

    # Validate that the specified vision model supports image input
    model_to_validate = vision_model or new_default.default_model_name
    if model_to_validate:
        if not model_supports_image_input(model_to_validate, new_default.provider):
            raise ValueError(
                f"Model '{model_to_validate}' for provider '{new_default.provider}' does not support image input"
            )
    else:
        raise ValueError(
            f"Model '{vision_model}' is not a valid model for provider '{new_default.provider}'"
        )

    existing_default = db_session.scalar(
        select(LLMProviderModel).where(
            LLMProviderModel.is_default_vision_provider == True  # noqa: E712
        )
    )
    if existing_default:
        existing_default.is_default_vision_provider = None
        # required to ensure that the below does not cause a unique constraint violation
        db_session.flush()

    new_default.is_default_vision_provider = True
    new_default.default_vision_model = vision_model
    db_session.commit()


def fetch_auto_mode_providers(db_session: Session) -> list[LLMProviderModel]:
    """Fetch all LLM providers that are in Auto mode."""
    return list(
        db_session.scalars(
            select(LLMProviderModel)
            .where(LLMProviderModel.is_auto_mode == True)  # noqa: E712
            .options(selectinload(LLMProviderModel.model_configurations))
        ).all()
    )


def sync_auto_mode_models(
    db_session: Session,
    provider: LLMProviderModel,
    llm_recommendations: LLMRecommendations,
) -> int:
    """Sync models from GitHub config to a provider in Auto mode.

    In Auto mode, the model list and default are controlled by GitHub config.
    The schema has:
    - default_model: The default model config (always visible)
    - additional_visible_models: List of additional visible models

    Admin only provides API credentials.

    Args:
        db_session: Database session
        provider: LLM provider in Auto mode
        github_config: Configuration from GitHub

    Returns:
        The number of changes made.
    """
    changes = 0

    # Build the list of all visible models from the config
    # All models in the config are visible (default + additional_visible_models)
    recommended_visible_models = llm_recommendations.get_visible_models(provider.name)
    recommended_visible_model_names = [
        model.name for model in recommended_visible_models
    ]

    # Get existing models
    existing_models: dict[str, ModelConfiguration] = {
        mc.name: mc
        for mc in db_session.scalars(
            select(ModelConfiguration).where(
                ModelConfiguration.llm_provider_id == provider.id
            )
        ).all()
    }

    # Remove models that are no longer in GitHub config
    for model_name, model in existing_models.items():
        if model_name not in recommended_visible_model_names:
            db_session.delete(model)
            changes += 1

    # Add or update models from GitHub config
    for model_config in recommended_visible_models:
        if model_config.name in existing_models:
            # Update existing model
            existing = existing_models[model_config.name]
            # Check each field for changes
            updated = False
            if existing.display_name != model_config.display_name:
                existing.display_name = model_config.display_name
                updated = True
            # All models in the config are visible
            if not existing.is_visible:
                existing.is_visible = True
                updated = True
            if updated:
                changes += 1
        else:
            # Add new model - all models from GitHub config are visible
            new_model = ModelConfiguration(
                llm_provider_id=provider.id,
                name=model_config.name,
                display_name=model_config.display_name,
                is_visible=True,
            )
            db_session.add(new_model)
            changes += 1

    # In Auto mode, default model is always set from GitHub config
    default_model = llm_recommendations.get_default_model(provider.name)
    if default_model and provider.default_model_name != default_model.name:
        provider.default_model_name = default_model.name
        changes += 1

    db_session.commit()
    return changes
