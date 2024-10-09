from slack_sdk import WebClient

from danswer.connectors.slack.connector import make_paginated_slack_api_call_w_retries


def fetch_user_id_to_email_map(
    slack_client: WebClient,
) -> dict[str, str]:
    user_id_to_email_map = {}
    for user_info in make_paginated_slack_api_call_w_retries(
        slack_client.users_list,
    ):
        for user in user_info.get("members", []):
            if user.get("profile", {}).get("email"):
                user_id_to_email_map[user.get("id")] = user.get("profile", {}).get(
                    "email"
                )
    return user_id_to_email_map
