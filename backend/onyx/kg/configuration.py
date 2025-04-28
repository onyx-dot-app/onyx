from onyx.configs.kg_configs import USE_KG_APPROACH
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entity_type import populate_default_employee_account_information
from onyx.db.entity_type import (
    populate_default_primary_grounded_entity_type_information,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def populate_default_grounded_entity_types() -> None:
    if not USE_KG_APPROACH:
        logger.error(
            "KG approach is not enabled, the entity types cannot be populated."
        )
        raise Exception(
            "KG approach is not enabled, the entity types cannot be populated."
        )

    with get_session_with_current_tenant() as db_session:
        populate_default_primary_grounded_entity_type_information(db_session)

        db_session.commit()

    return None


def populate_default_account_employee_definitions() -> None:
    if not USE_KG_APPROACH:
        logger.error(
            "KG approach is not enabled, the entity types cannot be populated."
        )
        raise Exception(
            "KG approach is not enabled, the entity types cannot be populated."
        )

    with get_session_with_current_tenant() as db_session:
        populate_default_employee_account_information(db_session)

        db_session.commit()

    return None
