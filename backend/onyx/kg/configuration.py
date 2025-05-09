import os

from passlib.exc import PasswordSizeError
from passlib.pwd import genword
from sqlalchemy import text

from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entity_type import populate_default_employee_account_information
from onyx.db.entity_type import (
    populate_default_primary_grounded_entity_type_information,
)
from onyx.db.kg_config import get_kg_enablement
from onyx.db.kg_config import KGConfigSettings
from onyx.utils.logger import setup_logger

KG_READONLY_DB_USER = os.getenv("KG_READONLY_DB_USER")
KG_READONLY_DB_PASSWORD = os.getenv("KG_READONLY_DB_PASSWORD")

logger = setup_logger()


def populate_default_grounded_entity_types() -> None:
    with get_session_with_current_tenant() as db_session:
        if not get_kg_enablement(db_session):
            logger.error(
                "KG approach is not enabled, the entity types cannot be populated."
            )
            raise Exception(
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
            raise Exception(
                "KG approach is not enabled, the entity types cannot be populated."
            )

        populate_default_employee_account_information(db_session)

        db_session.commit()

    return None


def create_kg_readonly_user() -> None:

    with get_session_with_current_tenant() as db_session:
        _USE_KG_APPROACH = get_kg_enablement(db_session)

    if not _USE_KG_APPROACH:
        logger.error(
            "KG approach is not enabled, the entity types cannot be populated."
        )
        raise Exception(
            "KG approach is not enabled, the entity types cannot be populated."
        )
    if not (KG_READONLY_DB_USER and KG_READONLY_DB_PASSWORD):
        logger.error("KG_READONLY_DB_USER or KG_READONLY_DB_PASSWORD is not set")
        raise Exception("KG_READONLY_DB_USER or KG_READONLY_DB_PASSWORD is not set")

    try:
        # Validate password length and complexity
        genword(
            length=13, charset="ascii_72"
        )  # This will raise PasswordSizeError if too short
        # Additional checks can be added here if needed
    except PasswordSizeError:
        logger.error("KG_READONLY_DB_PASSWORD is too short or too weak")
        raise Exception("KG_READONLY_DB_PASSWORD is too short or too weak")

    with get_session_with_current_tenant() as db_session:
        db_session.execute(
            text(
                f"CREATE USER {KG_READONLY_DB_USER} WITH PASSWORD '{KG_READONLY_DB_PASSWORD}';"
            )
        )
        db_session.commit()

    return None


def execute_kg_setting_tests(kg_config_settings: KGConfigSettings) -> None:
    if not kg_config_settings.KG_ENABLED:
        raise ValueError("KG is not enabled")
    if not kg_config_settings.KG_VENDOR:
        raise ValueError("KG_VENDOR is not set")
    if not kg_config_settings.KG_VENDOR_DOMAINS:
        raise ValueError("KG_VENDOR_DOMAINS is not set")
