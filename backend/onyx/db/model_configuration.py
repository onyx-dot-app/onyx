"""Model configuration queries kept apart from `onyx.db.llm`, which imports
`onyx.llm.utils` and so cannot be imported from there without a cycle."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import LLMProvider, ModelConfiguration


def fetch_model_configuration_by_provider_id_and_name(
    db_session: Session, llm_provider_id: int, model_name: str
) -> ModelConfiguration | None:
    return db_session.scalar(
        select(ModelConfiguration).where(
            ModelConfiguration.llm_provider_id == llm_provider_id,
            ModelConfiguration.name == model_name,
        )
    )


def fetch_model_configuration_by_name_and_provider(
    db_session: Session,
    model_name: str,
    provider: str,
) -> ModelConfiguration | None:
    return db_session.scalar(
        select(ModelConfiguration)
        .join(
            LLMProvider,
            ModelConfiguration.llm_provider_id == LLMProvider.id,
        )
        .where(
            ModelConfiguration.name == model_name,
            LLMProvider.provider == provider,
        )
    )
