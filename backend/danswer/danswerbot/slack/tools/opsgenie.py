import os
import re
from typing import Optional
from urllib.parse import quote

import requests

from danswer.db.models import ChannelConfig
from danswer.utils.logger import setup_logger

logger = setup_logger()

# OpsGenie API configuration
OPSGENIE_API_KEY = os.environ.get("OPSGENIE_API_KEY")
OPSGENIE_BASE_URL = "https://api.opsgenie.com/v2"

# Schedule name validation pattern - alphanumeric, hyphens, underscores, and spaces allowed
SCHEDULE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9-_ ]+$")


def get_dri_on_call(channel_config: ChannelConfig) -> Optional[str]:
    """
    Get the DRI on call for a given channel by looking up the OpsGenie schedule.

    Args:
        channel_config: The channel configuration containing the OpsGenie schedule name

    Returns:
        The name of the DRI on call, or None if not found
    """
    if not OPSGENIE_API_KEY:
        logger.error("OpsGenie API key not configured")
        return None

    # Get and validate the schedule name from channel config
    schedule_name = channel_config.get("opsgenie_schedule")
    if not schedule_name:
        logger.warning("No OpsGenie schedule configured for this channel")
        return None

    # Trim whitespace and validate schedule name format
    schedule_name = schedule_name.strip()
    if not SCHEDULE_NAME_PATTERN.match(schedule_name):
        logger.error(f"Invalid schedule name format: {schedule_name}")
        return None

    try:
        headers = {
            "Authorization": f"GenieKey {OPSGENIE_API_KEY}",
            "Content-Type": "application/json",
        }

        encoded_schedule_name = quote(
            schedule_name
        )  # quote is used to encode the schedule name for the URL
        oncall_url = f"{OPSGENIE_BASE_URL}/schedules/{encoded_schedule_name}/on-calls?scheduleIdentifierType=name&flat=true"

        try:
            response = requests.get(oncall_url, headers=headers, timeout=10)
            response.raise_for_status()
        except requests.exceptions.Timeout:
            logger.error("Timeout while fetching OpsGenie data")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching OpsGenie data: {str(e)}")
            return None

        try:
            response_data = response.json()
        except ValueError as e:
            logger.error(f"Invalid JSON response from OpsGenie: {str(e)}")
            return None

        try:
            oncall_data = response_data.get("data", {})
            participants = oncall_data.get("onCallRecipients", [])

            if not participants:
                logger.warning(
                    f"No on-call participants found for schedule: {schedule_name}"
                )
                return None

            # Get the first participant's name
            participant = participants[0]
            return participant

        except (KeyError, IndexError) as e:
            logger.error(f"Unexpected response format from OpsGenie: {str(e)}")
            return None

    except Exception as e:
        logger.error(f"Unexpected error in OpsGenie integration: {str(e)}")
        return None
