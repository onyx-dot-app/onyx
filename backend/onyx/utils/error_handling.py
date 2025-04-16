"""
Standardized error handling utilities.
"""

from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from onyx.utils.logger import setup_logger

logger = setup_logger()


def handle_connector_error(e: Exception, context: str) -> None:
    """
    Standard error handling for connectors.

    Args:
        e: The exception that was raised
        context: A description of where the error occurred

    Raises:
        The original exception if CONTINUE_ON_CONNECTOR_FAILURE is False
    """
    logger.error(f"Error in {context}: {e}", exc_info=e)
    if not CONTINUE_ON_CONNECTOR_FAILURE:
        raise
