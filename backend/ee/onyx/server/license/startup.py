from pathlib import Path

from ee.onyx.configs.app_configs import ONYX_LICENSE_FILE
from ee.onyx.utils.license import normalize_license_file, verify_and_store_license
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


def seed_license_from_file() -> None:
    if MULTI_TENANT or not ONYX_LICENSE_FILE:
        return

    try:
        license_data = normalize_license_file(
            Path(ONYX_LICENSE_FILE).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValueError):
        logger.error("Could not read ONYX_LICENSE_FILE. Keeping the stored license.")
        return

    if not license_data:
        logger.error("ONYX_LICENSE_FILE is empty. Keeping the stored license.")
        return

    with get_session_with_current_tenant() as db_session:
        try:
            verify_and_store_license(db_session, license_data)
        except ValueError:
            logger.error("ONYX_LICENSE_FILE is invalid. Keeping the stored license.")
            return

    logger.info("Processed ONYX_LICENSE_FILE.")
