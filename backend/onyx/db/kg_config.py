from datetime import datetime
from enum import Enum

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.models import KGConfig
from onyx.kg.models import KGConfigSettings
from onyx.kg.models import KGConfigVars
from onyx.server.kg.models import EnableKGConfigRequest
from onyx.server.kg.models import KGConfig as KGConfigAPIModel


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
    # TODO (raunakab):
    # Cleanup.

    results = db_session.query(KGConfig).all()

    kg_config_settings = KGConfigSettings()
    for result in results:
        if result.kg_variable_name == "KG_ENABLED":
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
            if not result.kg_variable_values:
                kg_max_coverage_days_str: str | int = 1000000

            else:
                kg_max_coverage_days_str = result.kg_variable_values[0] or "1000000"
                if not kg_max_coverage_days_str.isdigit():
                    raise ValueError(
                        f"KG_MAX_COVERAGE_DAYS is not a number: {kg_max_coverage_days_str}"
                    )

            kg_config_settings.KG_MAX_COVERAGE_DAYS = int(kg_max_coverage_days_str)

        elif result.kg_variable_name == KGConfigVars.KG_EXTRACTION_IN_PROGRESS:
            kg_config_settings.KG_EXTRACTION_IN_PROGRESS = (
                result.kg_variable_values[0] == "true"
            )
        elif result.kg_variable_name == KGConfigVars.KG_CLUSTERING_IN_PROGRESS:
            kg_config_settings.KG_CLUSTERING_IN_PROGRESS = (
                result.kg_variable_values[0] == "true"
            )

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
    kg_variable_name = "KG_EXTRACTION_IN_PROGRESS"  # Default value

    if processing_type == KGProcessingType.CLUSTERING:
        kg_variable_name = "KG_CLUSTERING_IN_PROGRESS"

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

    kg_variable_name = "KG_EXTRACTION_IN_PROGRESS"  # Default value
    if processing_type == KGProcessingType.CLUSTERING:
        kg_variable_name = "KG_CLUSTERING_IN_PROGRESS"

    config = (
        db_session.query(KGConfig)
        .filter(KGConfig.kg_variable_name == kg_variable_name)
        .first()
    )

    if not config:
        return False

    return config.kg_variable_values[0] == "true"


# API helpers


def get_kg_config(db_session: Session) -> KGConfigAPIModel:
    config = get_kg_config_settings(db_session=db_session)
    return KGConfigAPIModel.from_kg_config_settings(config)


def disable_kg(db_session: Session) -> None:
    var = (
        db_session.query(KGConfig)
        .filter(KGConfig.kg_variable_name == KGConfigVars.KG_ENABLED)
        .first()
    )

    values = [bool_to_string(False)]

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


def enable_kg(
    db_session: Session,
    enable_req: EnableKGConfigRequest,
) -> None:
    # cannot be empty string
    if not enable_req.vendor:
        raise ValueError(
            f"KG vendor must be specified; instead got {enable_req.vendor=}"
        )

    # cannot be empty list
    if not enable_req.vendor_domains:
        raise ValueError(
            f"KG vendor domains must be specified; instead got {enable_req.vendor_domains=}"
        )

    vars = [
        KGConfig(
            kg_variable_name=KGConfigVars.KG_ENABLED,
            kg_variable_values=[bool_to_string(True)],
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


def bool_to_string(b: bool) -> str:
    return "true" if b else "false"
