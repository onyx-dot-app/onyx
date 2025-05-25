from typing import Any
from typing import Optional

import requests

from onyx.utils.logger import setup_logger
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestUser

logger = setup_logger()


def _format_request_exception_message(
    e: requests.exceptions.RequestException, context: str
) -> str:
    """Formats an error message for a RequestException."""
    error_msg = f"Error {context}: {e}"
    if hasattr(e, "response") and e.response is not None:
        error_msg += f" | Response body: {e.response.text}"
    return error_msg


def create_slack_bot(
    bot_token: str,
    app_token: str,
    user_performing_action: DATestUser,
    enabled: bool = True,
    name: str = "test-slack-bot",
) -> dict[str, Any]:
    """Create a Slack bot using the provided tokens and user information."""
    body = {
        "name": name,
        "enabled": enabled,
        "bot_token": bot_token,
        "app_token": app_token,
    }
    try:
        response = requests.post(
            url=f"{API_SERVER_URL}/manage/admin/slack-app/bots",
            headers=user_performing_action.headers,
            json=body,
        )
        response.raise_for_status()
        response_json = response.json()
        logger.info(f"Slack bot created successfully: {response_json}")
        return response_json
    except requests.exceptions.RequestException as e:
        error_message = _format_request_exception_message(e, "creating Slack bot")
        logger.error(error_message)
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise


def list_slack_channel_configs(
    bot_id: int,
    user_performing_action: DATestUser,
) -> list[dict[str, Any]]:
    """Lists Slack channel configurations for a given bot ID."""
    try:
        response = requests.get(
            url=f"{API_SERVER_URL}/manage/admin/slack-app/bots/{bot_id}/config",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        response_json = response.json()
        logger.info(
            f"Successfully listed Slack channel configs for bot {bot_id}: {response_json}"
        )
        return response_json
    except requests.exceptions.RequestException as e:
        error_message = _format_request_exception_message(
            e, f"listing Slack channel configs for bot {bot_id}"
        )
        logger.error(error_message)
        raise
    except Exception as e:
        logger.error(f"Unexpected error listing Slack channel configs: {e}")
        raise


def update_slack_channel_config(
    config_id: int,
    update_data: dict[str, Any],
    user_performing_action: DATestUser,
) -> dict[str, Any]:
    """Updates a specific Slack channel configuration."""
    try:
        response = requests.patch(
            url=f"{API_SERVER_URL}/manage/admin/slack-app/channel/{config_id}",
            headers=user_performing_action.headers,
            json=update_data,
        )
        response.raise_for_status()
        response_json = response.json()
        logger.info(
            f"Successfully updated Slack channel config {config_id}: {response_json}"
        )
        return response_json
    except requests.exceptions.RequestException as e:
        error_message = _format_request_exception_message(
            e, f"updating Slack channel config {config_id}"
        )
        logger.error(error_message)
        raise
    except Exception as e:
        logger.error(f"Unexpected error updating Slack channel config: {e}")
        raise


def list_slack_channels_from_api(
    bot_id: int,
    user_performing_action: DATestUser,
) -> list[dict[str, Any]]:
    """Lists Slack channels available to the bot via the Slack API."""
    try:
        response = requests.get(
            url=f"{API_SERVER_URL}/manage/admin/slack-app/bots/{bot_id}/channels",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        response_json = response.json()
        logger.info(
            f"Successfully listed Slack channels for bot {bot_id} from API: {response_json}"
        )
        return response_json
    except requests.exceptions.RequestException as e:
        error_message = _format_request_exception_message(
            e, f"listing Slack channels from API for bot {bot_id}"
        )
        logger.error(error_message)
        raise
    except Exception as e:
        logger.error(f"Unexpected error listing Slack channels from API: {e}")
        raise


def create_standard_answer_category(
    category_name: str,
    user_performing_action: DATestUser,
) -> dict[str, Any]:
    """Creates a standard answer category."""
    body = {"name": category_name}
    try:
        response = requests.post(
            url=f"{API_SERVER_URL}/manage/admin/standard-answer/category",
            headers=user_performing_action.headers,
            json=body,
        )
        response.raise_for_status()
        response_json = response.json()
        logger.info(f"Standard answer category created successfully: {response_json}")
        return response_json
    except requests.exceptions.RequestException as e:
        error_message = _format_request_exception_message(
            e, f"creating standard answer category '{category_name}'"
        )
        logger.error(error_message)
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating standard answer category: {e}")
        raise


def create_standard_answer(
    keyword: str,
    answer: str,
    category_ids: list[int],
    user_performing_action: DATestUser,
    match_regex: bool = False,
    match_any_keywords: bool = False,
) -> dict[str, Any]:
    """Creates a standard answer."""
    body = {
        "keyword": keyword,
        "answer": answer,
        "categories": category_ids,
        "match_regex": match_regex,
        "match_any_keywords": match_any_keywords,
    }
    try:
        response = requests.post(
            url=f"{API_SERVER_URL}/manage/admin/standard-answer",
            headers=user_performing_action.headers,
            json=body,
        )
        response.raise_for_status()
        response_json = response.json()
        logger.info(f"Standard answer created successfully: {response_json}")
        return response_json
    except requests.exceptions.RequestException as e:
        error_message = _format_request_exception_message(
            e, f"creating standard answer with keyword '{keyword}'"
        )
        logger.error(error_message)
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating standard answer: {e}")
        raise


def create_standard_answer_with_category(
    category_name: str,
    keyword: str,
    answer: str,
    user_performing_action: DATestUser,
    match_regex: bool = False,
    match_any_keywords: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Creates a standard answer category and then a standard answer using that category."""
    # Create the category first
    category = create_standard_answer_category(
        category_name=category_name,
        user_performing_action=user_performing_action,
    )
    category_id = category.get("id")
    if category_id is None:
        raise ValueError("Failed to get ID from created category")

    # Create the standard answer using the new category ID
    standard_answer = create_standard_answer(
        keyword=keyword,
        answer=answer,
        category_ids=[category_id],
        user_performing_action=user_performing_action,
        match_regex=match_regex,
        match_any_keywords=match_any_keywords,
    )

    return category, standard_answer


def create_slack_channel_config(
    bot_id: int,
    channel_name: str,
    user_performing_action: DATestUser,
    config_data: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Creates a Slack channel config for a given bot and channel.
    """

    body = {
        "slack_bot_id": bot_id,
        "channel_name": channel_name,
        "response_type": "citations",
        "respond_tag_only": True,
    }

    if config_data:
        body.update(config_data)

    try:
        response = requests.post(
            url=f"{API_SERVER_URL}/manage/admin/slack-app/channel",
            headers=user_performing_action.headers,
            json=body,
        )
        response.raise_for_status()
        response_json = response.json()
        logger.info(f"Slack channel config created successfully: {response_json}")
        return response_json
    except requests.exceptions.RequestException as e:
        error_message = _format_request_exception_message(
            e, f"creating Slack channel config for channel '{channel_name}'"
        )
        logger.error(error_message)
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating Slack channel config: {e}")
        raise


def delete_slack_bot(
    bot_id: int,
    user_performing_action: DATestUser,
) -> None:
    """Deletes a Slack bot using the API."""
    try:
        response = requests.delete(
            url=f"{API_SERVER_URL}/manage/admin/slack-app/bots/{bot_id}",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        logger.info(f"Slack bot {bot_id} deleted successfully.")
    except requests.exceptions.RequestException as e:
        error_message = _format_request_exception_message(
            e, f"deleting Slack bot {bot_id}"
        )
        logger.error(error_message)
        raise
    except Exception as e:
        logger.error(f"Unexpected error deleting Slack bot {bot_id}: {e}")
        raise


def get_slack_bot(
    bot_id: int,
    user_performing_action: DATestUser,
) -> dict[str, Any]:
    """Fetches a Slack bot's details using the API."""
    try:
        response = requests.get(
            url=f"{API_SERVER_URL}/manage/admin/slack-app/bots/{bot_id}",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        bot_data = response.json()
    except requests.exceptions.RequestException as e:
        error_message = _format_request_exception_message(
            e, f"fetching Slack bot {bot_id} details for disabling"
        )
        logger.error(error_message)
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching Slack bot {bot_id}: {e}")
        raise
    logger.info(f"Fetched Slack bot {bot_id} details: {bot_data}")
    return bot_data


def update_slack_bot(
    bot_id: int,
    user_performing_action: DATestUser,
    update_body: dict[str, Any],
) -> dict[str, Any]:
    """Updates a Slack bot via the API."""
    try:
        response = requests.patch(
            url=f"{API_SERVER_URL}/manage/admin/slack-app/bots/{bot_id}",
            headers=user_performing_action.headers,
            json=update_body,
        )
        response.raise_for_status()
        response_json = response.json()
        logger.info(f"Slack bot {bot_id} updated successfully: {response_json}")
        return response_json
    except requests.exceptions.RequestException as e:
        error_message = _format_request_exception_message(
            e, f"updating Slack bot {bot_id}"
        )
        logger.error(error_message)
        raise
    except Exception as e:
        logger.error(f"Unexpected error updating Slack bot {bot_id}: {e}")
        raise
