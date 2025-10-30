from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.db.models import CloudEmbeddingProvider as CloudEmbeddingProviderModel
from onyx.db.models import DocumentSet
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


def get_personas_for_llm_provider(
    db_session: Session, llm_provider_id: int
) -> list[int]:
    """Return persona IDs that explicitly allow the given provider."""
    return list(
        db_session.scalars(
            select(LLMProvider__Persona.persona_id).where(
                LLMProvider__Persona.llm_provider_id == llm_provider_id
            )
        ).all()
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
) -> bool:
    """Check if a user may use an LLM provider.

    Args:
        provider: The LLM provider to check access for
        user_group_ids: Set of user group IDs the user belongs to
        persona: The persona being used (if any)

    Access logic:
    1. If is_public=True → everyone has access (public override)
    2. If is_public=False:
       - Both groups AND personas set → must satisfy BOTH (AND logic)
       - Only groups set → must be in one of the groups (OR across groups)
       - Only personas set → must use one of the personas (OR across personas)
       - Neither set → NOBODY has access (locked, admin-only)
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
        user_in_group = bool(user_group_ids & provider_group_ids)
        persona_allowed = persona.id in provider_persona_ids if persona else False
        return user_in_group and persona_allowed

    # Only groups set → user must be in one of the groups
    if has_groups:
        return bool(user_group_ids & provider_group_ids)

    # Only personas set → persona must be in allowed list
    if has_personas:
        return persona.id in provider_persona_ids if persona else False

    # Neither groups nor personas set, and not public → LOCKED (admin-only)
    return False


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
    existing_llm_provider.fast_default_model_name = (
        llm_provider_upsert_request.fast_default_model_name
    )
    existing_llm_provider.is_public = llm_provider_upsert_request.is_public
    existing_llm_provider.deployment_name = llm_provider_upsert_request.deployment_name

    if not existing_llm_provider.id:
        # If its not already in the db, we need to generate an ID by flushing
        db_session.flush()

    # Delete existing model configurations
    db_session.query(ModelConfiguration).filter(
        ModelConfiguration.llm_provider_id == existing_llm_provider.id
    ).delete(synchronize_session="fetch")

    db_session.flush()

    for model_configuration in llm_provider_upsert_request.model_configurations:
        db_session.execute(
            insert(ModelConfiguration)
            .values(
                llm_provider_id=existing_llm_provider.id,
                name=model_configuration.name,
                is_visible=model_configuration.is_visible,
                max_input_tokens=model_configuration.max_input_tokens,
                supports_image_input=model_configuration.supports_image_input,
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
) -> list[LLMProviderModel]:
    stmt = select(LLMProviderModel).options(
        selectinload(LLMProviderModel.model_configurations),
        selectinload(LLMProviderModel.groups),
        selectinload(LLMProviderModel.personas),
    )
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
