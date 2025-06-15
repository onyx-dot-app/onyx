from datetime import datetime
from enum import Enum

from sqlalchemy import exists
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.models import KGConfig
from onyx.kg.models import KGConfigSettings
from onyx.kg.models import KGConfigVars
from onyx.server.kg.models import EnableKGConfigRequest


class KGProcessingType(Enum):
    EXTRACTION = "extraction"
    CLUSTERING = "clustering"


def get_kg_exposed(db_session: Session) -> bool:
    return db_session.query(
        exists().where(
            KGConfig.kg_variable_name == KGConfigVars.KG_EXPOSED,
            KGConfig.kg_variable_values == ["true"],
        )
    ).scalar()


def get_kg_beta_persona_id(db_session: Session) -> int | None:
    """Get the ID of the KG Beta persona."""
    config = (
        db_session.query(KGConfig)
        .filter(KGConfig.kg_variable_name == KGConfigVars.KG_BETA_PERSONA_ID)
        .first()
    )

    if not config or not config.kg_variable_values:
        return None

    try:
        return int(config.kg_variable_values[0])
    except (ValueError, IndexError):
        return None


def set_kg_beta_persona_id(db_session: Session, persona_id: int | None) -> None:
    """Set the ID of the KG Beta persona."""
    value = [str(persona_id)] if persona_id is not None else []

    stmt = (
        pg_insert(KGConfig)
        .values(
            kg_variable_name=KGConfigVars.KG_BETA_PERSONA_ID,
            kg_variable_values=value,
        )
        .on_conflict_do_update(
            index_elements=["kg_variable_name"],
            set_=dict(kg_variable_values=value),
        )
    )

    db_session.execute(stmt)
    db_session.commit()


def get_kg_config_settings(db_session: Session) -> KGConfigSettings:
    # TODO (raunakab):
    # Cleanup.

    # TODO (joachim-danswer): restructure together with KGConfig redesign

    results = db_session.query(KGConfig).all()

    kg_config_settings = KGConfigSettings()
    for result in results:
        if result.kg_variable_name == KGConfigVars.KG_ENABLED:
            kg_config_settings.KG_ENABLED = result.kg_variable_values[0] == "true"
        elif result.kg_variable_name == KGConfigVars.KG_VENDOR:
            if len(result.kg_variable_values) > 0:
                kg_config_settings.KG_VENDOR = result.kg_variable_values[0]
            else:
                kg_config_settings.KG_VENDOR = None
        elif result.kg_variable_name == KGConfigVars.KG_VENDOR_DOMAINS:
            kg_config_settings.KG_VENDOR_DOMAINS = result.kg_variable_values
        elif result.kg_variable_name == KGConfigVars.KG_IGNORE_EMAIL_DOMAINS:
            kg_config_settings.KG_IGNORE_EMAIL_DOMAINS = result.kg_variable_values
        elif result.kg_variable_name == KGConfigVars.KG_COVERAGE_START:
            kg_coverage_start_str = result.kg_variable_values[0] or "1970-01-01"

            kg_config_settings.KG_COVERAGE_START = datetime.strptime(
                kg_coverage_start_str, "%Y-%m-%d"
            )

        elif result.kg_variable_name == KGConfigVars.KG_MAX_COVERAGE_DAYS:
            kg_max_coverage_days_str = result.kg_variable_values[0]
            if not kg_max_coverage_days_str.isdigit():
                raise ValueError(
                    f"KG_MAX_COVERAGE_DAYS is not a number: {kg_max_coverage_days_str}"
                )
            kg_config_settings.KG_MAX_COVERAGE_DAYS = max(
                0, int(kg_max_coverage_days_str)
            )

        elif result.kg_variable_name == KGConfigVars.KG_EXTRACTION_IN_PROGRESS:
            kg_config_settings.KG_EXTRACTION_IN_PROGRESS = (
                result.kg_variable_values[0] == "true"
            )
        elif result.kg_variable_name == KGConfigVars.KG_CLUSTERING_IN_PROGRESS:
            kg_config_settings.KG_CLUSTERING_IN_PROGRESS = (
                result.kg_variable_values[0] == "true"
            )
        elif result.kg_variable_name == KGConfigVars.KG_MAX_PARENT_RECURSION_DEPTH:
            kg_max_parent_recursion_depth_str = result.kg_variable_values[0]
            if not kg_max_parent_recursion_depth_str.isdigit():
                raise ValueError(
                    f"KG_MAX_PARENT_RECURSION_DEPTH is not a number: {kg_max_parent_recursion_depth_str}"
                )
            kg_config_settings.KG_MAX_PARENT_RECURSION_DEPTH = max(
                0, int(kg_max_parent_recursion_depth_str)
            )
        elif result.kg_variable_name == KGConfigVars.KG_EXPOSED:
            kg_config_settings.KG_EXPOSED = result.kg_variable_values[0] == "true"
        elif result.kg_variable_name == KGConfigVars.KG_BETA_PERSONA_ID:
            value = result.kg_variable_values[0] if result.kg_variable_values else None
            kg_config_settings.KG_BETA_PERSONA_ID = (
                int(value) if value and str(value).isdigit() else None
            )

    return kg_config_settings


def validate_kg_settings(kg_config_settings: KGConfigSettings) -> None:
    if not kg_config_settings.KG_ENABLED:
        raise ValueError("KG is not enabled")
    if not kg_config_settings.KG_VENDOR:
        raise ValueError("KG_VENDOR is not set")
    if not kg_config_settings.KG_VENDOR_DOMAINS:
        raise ValueError("KG_VENDOR_DOMAINS is not set")


def set_kg_processing_in_progress_status(
    db_session: Session, processing_type: KGProcessingType, in_progress: bool
) -> None:
    """
    Set the KG_EXTRACTION_IN_PROGRESS or KG_CLUSTERING_IN_PROGRESS configuration values.

    Args:
        db_session: The database session to use
        in_progress: Whether KG processing is in progress (True) or not (False)
    """
    # Convert boolean to string and wrap in list as required by the model
    value = [str(in_progress).lower()]

    kg_variable_name = KGConfigVars.KG_EXTRACTION_IN_PROGRESS.value  # Default value

    if processing_type == KGProcessingType.CLUSTERING:
        kg_variable_name = KGConfigVars.KG_CLUSTERING_IN_PROGRESS.value

    # Use PostgreSQL's upsert functionality
    stmt = (
        pg_insert(KGConfig)
        .values(kg_variable_name=str(kg_variable_name), kg_variable_values=value)
        .on_conflict_do_update(
            index_elements=["kg_variable_name"], set_=dict(kg_variable_values=value)
        )
    )

    db_session.execute(stmt)


def get_kg_processing_in_progress_status(
    db_session: Session, processing_type: KGProcessingType
) -> bool:
    """
    Get the current KG_EXTRACTION_IN_PROGRESS or KG_CLUSTERING_IN_PROGRESS configuration value.

    Args:
        db_session: The database session to use

    Returns:
        bool: True if KG processing is in progress, False otherwise
    """

    kg_variable_name = KGConfigVars.KG_EXTRACTION_IN_PROGRESS.value  # Default value
    if processing_type == KGProcessingType.CLUSTERING:
        kg_variable_name = KGConfigVars.KG_CLUSTERING_IN_PROGRESS.value

    config = (
        db_session.query(KGConfig)
        .filter(KGConfig.kg_variable_name == kg_variable_name)
        .first()
    )

    if not config:
        return False

    return config.kg_variable_values[0] == "true"


def enable_kg__commit(
    db_session: Session,
    enable_req: EnableKGConfigRequest,
) -> None:
    validate_kg_settings(
        KGConfigSettings(
            KG_ENABLED=True,
            KG_VENDOR=enable_req.vendor,
            KG_VENDOR_DOMAINS=enable_req.vendor_domains,
            KG_IGNORE_EMAIL_DOMAINS=enable_req.ignore_domains,
            KG_COVERAGE_START=enable_req.coverage_start,
        )
    )

    vars = [
        KGConfig(
            kg_variable_name=KGConfigVars.KG_ENABLED,
            kg_variable_values=["true"],
        ),
        KGConfig(
            kg_variable_name=KGConfigVars.KG_VENDOR,
            kg_variable_values=[enable_req.vendor],
        ),
        KGConfig(
            kg_variable_name=KGConfigVars.KG_VENDOR_DOMAINS,
            kg_variable_values=enable_req.vendor_domains,
        ),
        KGConfig(
            kg_variable_name=KGConfigVars.KG_IGNORE_EMAIL_DOMAINS,
            kg_variable_values=enable_req.ignore_domains,
        ),
        KGConfig(
            kg_variable_name=KGConfigVars.KG_COVERAGE_START,
            kg_variable_values=[enable_req.coverage_start.strftime("%Y-%m-%d")],
        ),
        KGConfig(
            kg_variable_name=KGConfigVars.KG_MAX_COVERAGE_DAYS,
            kg_variable_values=["10000"],  # TODO: revisit coverage days
        ),
    ]

    for var in vars:
        existing_var = (
            db_session.query(KGConfig)
            .filter(KGConfig.kg_variable_name == var.kg_variable_name)
            .first()
        )
        if not existing_var:
            db_session.add(var)
            continue

        db_session.query(KGConfig).filter(
            KGConfig.kg_variable_name == var.kg_variable_name
        ).update(
            {"kg_variable_values": var.kg_variable_values},
            synchronize_session=False,
        )

    db_session.commit()


def disable_kg__commit(db_session: Session) -> None:
    var = (
        db_session.query(KGConfig)
        .filter(KGConfig.kg_variable_name == KGConfigVars.KG_ENABLED)
        .first()
    )

    values = ["false"]

    if var:
        db_session.query(KGConfig).where(
            KGConfig.kg_variable_name == KGConfigVars.KG_ENABLED
        ).update(
            {"kg_variable_values": values},
            synchronize_session=False,
        )
    else:
        db_session.add(
            KGConfig(
                kg_variable_name=KGConfigVars.KG_ENABLED,
                kg_variable_values=values,
            )
        )

    db_session.commit()
