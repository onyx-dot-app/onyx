from sqlalchemy import delete, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from onyx.db.models import ImageProcessingSettings, ModelConfiguration


def fetch_image_processing_settings(
    db_session: Session,
) -> ImageProcessingSettings | None:
    """The single image processing row, or None when the feature is off."""
    return db_session.scalar(
        select(ImageProcessingSettings).options(
            selectinload(ImageProcessingSettings.model_configuration).selectinload(
                ModelConfiguration.llm_provider
            )
        )
    )


def upsert_image_processing_settings(
    db_session: Session,
    model_configuration_id: int,
    max_size_mb: int,
) -> ImageProcessingSettings:
    """Turn image processing on, or repoint it. The caller checks that the
    model can take images; the rule lives with the provider listing."""
    model_configuration = db_session.get(ModelConfiguration, model_configuration_id)
    if model_configuration is None:
        raise ValueError(f"model_configuration id={model_configuration_id} not found")
    if max_size_mb <= 0:
        raise ValueError("max_size_mb must be positive")

    # At most one row exists (a unique index over the constant `true`), so
    # two concurrent enables race to insert it. The conflict target is that
    # index, and the loser updates the row instead of failing.
    stmt = (
        insert(ImageProcessingSettings)
        .values(
            model_configuration_id=model_configuration_id,
            max_size_mb=max_size_mb,
        )
        .on_conflict_do_update(
            index_elements=[literal_column("(true)")],
            set_={
                "model_configuration_id": model_configuration_id,
                "max_size_mb": max_size_mb,
            },
        )
        .returning(ImageProcessingSettings)
    )
    row = db_session.scalars(stmt, execution_options={"populate_existing": True}).one()
    db_session.commit()
    return row


def delete_image_processing_settings(db_session: Session) -> None:
    """Turn image processing off. A no-op when it is already off."""
    db_session.execute(delete(ImageProcessingSettings))
    db_session.commit()
