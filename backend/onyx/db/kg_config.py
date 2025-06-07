from datetime import datetime
from enum import Enum

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.models import KGConfig
from onyx.kg.models import KGConfigSettings
from onyx.kg.models import KGConfigVars


class KGProcessingType(Enum):

    EXTRACTION = "extraction"
    CLUSTERING = "clustering"


def get_kg_enablement(db_session: Session) -> bool:
    check = (
        db_session.query(KGConfig.kg_variable_values)
        .filter(
            KGConfig.kg_variable_name == "KG_ENABLED"
            and KGConfig.kg_variable_values == ["true"]
        )
        .first()
    )
    return check is not None


def get_kg_config_settings(db_session: Session) -> KGConfigSettings:
    # TODO: restructure togethert with KGConfig redesign
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

    return kg_config_settings


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
