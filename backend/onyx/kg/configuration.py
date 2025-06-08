from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entity_type import populate_default_employee_account_information
from onyx.db.entity_type import (
    populate_default_primary_grounded_entity_type_information,
)
from onyx.db.kg_config import get_kg_enablement
from onyx.db.kg_config import KGConfigSettings
from onyx.utils.logger import setup_logger

logger = setup_logger()


def populate_default_grounded_entity_types() -> None:
    with get_session_with_current_tenant() as db_session:
        if not get_kg_enablement(db_session):
            logger.error(
                "KG approach is not enabled, the entity types cannot be populated."
            )
            raise ValueError(
                "KG approach is not enabled, the entity types cannot be populated."
            )

        populate_default_primary_grounded_entity_type_information(db_session)

        db_session.commit()

    return None


def populate_default_account_employee_definitions() -> None:
    with get_session_with_current_tenant() as db_session:
        if not get_kg_enablement(db_session):
            logger.error(
                "KG approach is not enabled, the entity types cannot be populated."
            )
            raise ValueError(
                "KG approach is not enabled, the entity types cannot be populated."
            )

        populate_default_employee_account_information(db_session)

        db_session.commit()

    return None


def validate_kg_settings(kg_config_settings: KGConfigSettings) -> None:
    if not kg_config_settings.KG_ENABLED:
        raise ValueError("KG is not enabled")
    if not kg_config_settings.KG_VENDOR:
        raise ValueError("KG_VENDOR is not set")
    if not kg_config_settings.KG_VENDOR_DOMAINS:
        raise ValueError("KG_VENDOR_DOMAINS is not set")
