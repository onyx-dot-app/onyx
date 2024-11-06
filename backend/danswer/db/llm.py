from sqlalchemy import delete
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.db.models import CloudEmbeddingProvider as CloudEmbeddingProviderModel
from danswer.db.models import DocumentSet
from danswer.db.models import LLMProvider as LLMProviderModel
from danswer.db.models import LLMProvider__UserGroup
from danswer.db.models import SearchSettings
from danswer.db.models import Tool as ToolModel
from danswer.db.models import User
from danswer.db.models import User__UserGroup
from danswer.server.manage.embedding.models import CloudEmbeddingProvider
from danswer.server.manage.embedding.models import CloudEmbeddingProviderCreationRequest
from danswer.server.manage.llm.models import FullLLMProvider
from danswer.server.manage.llm.models import LLMProviderUpsertRequest
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
    llm_provider: LLMProviderUpsertRequest,
    db_session: Session,
) -> FullLLMProvider:
    existing_llm_provider = db_session.scalar(
        select(LLMProviderModel).where(LLMProviderModel.name == llm_provider.name)
    )

    if not existing_llm_provider:
        existing_llm_provider = LLMProviderModel(name=llm_provider.name)
        db_session.add(existing_llm_provider)

    existing_llm_provider.provider = llm_provider.provider
    existing_llm_provider.api_key = llm_provider.api_key
    existing_llm_provider.api_base = llm_provider.api_base
    existing_llm_provider.api_version = llm_provider.api_version
    existing_llm_provider.custom_config = llm_provider.custom_config
    existing_llm_provider.default_model_name = llm_provider.default_model_name
    existing_llm_provider.fast_default_model_name = llm_provider.fast_default_model_name
    existing_llm_provider.model_names = llm_provider.model_names
    existing_llm_provider.is_public = llm_provider.is_public
    existing_llm_provider.display_model_names = llm_provider.display_model_names
    existing_llm_provider.deployment_name = llm_provider.deployment_name

    if not existing_llm_provider.id:
        # If its not already in the db, we need to generate an ID by flushing
        db_session.flush()

    # Make sure the relationship table stays up to date
    update_group_llm_provider_relationships__no_commit(
        llm_provider_id=existing_llm_provider.id,
        group_ids=llm_provider.groups,
        db_session=db_session,
    )
    full_llm_provider = FullLLMProvider.from_model(existing_llm_provider)

    db_session.commit()

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
    user: User | None = None,
) -> list[LLMProviderModel]:
    if not user:
        return list(db_session.scalars(select(LLMProviderModel)).all())
    stmt = select(LLMProviderModel).distinct()
    user_groups_select = select(User__UserGroup.user_group_id).where(
        User__UserGroup.user_id == user.id
    )
    access_conditions = or_(
        LLMProviderModel.is_public,
        LLMProviderModel.id.in_(  # User is part of a group that has access
            select(LLMProvider__UserGroup.llm_provider_id).where(
                LLMProvider__UserGroup.user_group_id.in_(user_groups_select)  # type: ignore
            )
        ),
    )
    stmt = stmt.where(access_conditions)

    return list(db_session.scalars(stmt).all())


def fetch_embedding_provider(
    db_session: Session, provider_type: EmbeddingProvider
) -> CloudEmbeddingProviderModel | None:
    return db_session.scalar(
        select(CloudEmbeddingProviderModel).where(
            CloudEmbeddingProviderModel.provider_type == provider_type
        )
    )


def fetch_default_provider(db_session: Session) -> FullLLMProvider | None:
    provider_model = db_session.scalar(
        select(LLMProviderModel).where(
            LLMProviderModel.is_default_provider == True  # noqa: E712
        )
    )
    if not provider_model:
        return None
    return FullLLMProvider.from_model(provider_model)


def fetch_provider(db_session: Session, provider_name: str) -> FullLLMProvider | None:
    provider_model = db_session.scalar(
        select(LLMProviderModel).where(LLMProviderModel.name == provider_name)
    )
    if not provider_model:
        return None
    return FullLLMProvider.from_model(provider_model)


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
    # Remove LLMProvider's dependent relationships
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
