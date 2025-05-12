import os
from typing import Optional
from urllib.parse import quote

import requests

from danswer.db.models import ChannelConfig
from danswer.utils.logger import setup_logger

logger = setup_logger()

# OpsGenie API configuration
OPSGENIE_API_KEY = os.environ.get("OPSGENIE_API_KEY")
OPSGENIE_BASE_URL = "https://api.opsgenie.com/v2"


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

    # Get the schedule name from channel config
    schedule_name = channel_config.get("opsgenie_schedule")
    if not schedule_name:
        logger.warning("No OpsGenie schedule configured for this channel")
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
        response = requests.get(oncall_url, headers=headers)
        response.raise_for_status()

        oncall_data = response.json().get("data", {})
        participants = oncall_data.get("onCallRecipients", [])

        if not participants:
            logger.warning(
                f"No on-call participants found for schedule: {schedule_name}"
            )
            return None

        # Get the first participant's name
        participant = participants[0]
        return participant

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching OpsGenie data: {str(e)}")
        return None
