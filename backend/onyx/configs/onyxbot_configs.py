import os
from urllib.parse import urlparse

from onyx.utils.logger import setup_logger

logger = setup_logger()

_DEFAULT_SLACK_API_URL = "https://slack.com/api/"
# Slack clouds the bot may send its tokens to. GovSlack is Slack's FedRAMP
# cloud on slack-gov.com. Any other host is rejected, so a typo cannot send a
# bot token to an arbitrary server.
_TRUSTED_SLACK_API_HOSTS = frozenset({"slack.com", "slack-gov.com"})


def _load_slack_api_url() -> str:
    raw = (os.environ.get("SLACK_API_URL") or "").strip()
    if not raw:
        return _DEFAULT_SLACK_API_URL
    parsed = urlparse(raw)
    if parsed.scheme != "https" or parsed.hostname not in _TRUSTED_SLACK_API_HOSTS:
        logger.error(
            "Ignoring SLACK_API_URL=%r: expected https on one of %s. "
            "Falling back to %s.",
            raw,
            sorted(_TRUSTED_SLACK_API_HOSTS),
            _DEFAULT_SLACK_API_URL,
        )
        return _DEFAULT_SLACK_API_URL
    return f"https://{parsed.hostname}/api/"


#####
# Onyx Slack Bot Configs
#####
# Slack Web API base the bot calls. Set to https://slack-gov.com/api/ for
# GovSlack. Socket Mode follows it, since apps.connections.open is a Web API
# call.
SLACK_API_URL = _load_slack_api_url()
ONYX_BOT_NUM_RETRIES = int(os.environ.get("ONYX_BOT_NUM_RETRIES", "5"))
# Number of docs to display in "Reference Documents"
ONYX_BOT_NUM_DOCS_TO_DISPLAY = int(os.environ.get("ONYX_BOT_NUM_DOCS_TO_DISPLAY", "5"))
# If the LLM fails to answer, Onyx can still show the "Reference Documents"
ONYX_BOT_DISABLE_DOCS_ONLY_ANSWER = os.environ.get(
    "ONYX_BOT_DISABLE_DOCS_ONLY_ANSWER", ""
).lower() not in ["false", ""]
# When Onyx is considering a message, what emoji does it react with
ONYX_BOT_REACT_EMOJI = os.environ.get("ONYX_BOT_REACT_EMOJI") or "eyes"
# When User needs more help, what should the emoji be
ONYX_BOT_FOLLOWUP_EMOJI = os.environ.get("ONYX_BOT_FOLLOWUP_EMOJI") or "sos"
# What kind of message should be shown when someone gives an AI answer feedback to OnyxBot
# Defaults to Private if not provided or invalid
# Private: Only visible to user clicking the feedback
# Anonymous: Public but anonymous
# Public: Visible with the user name who submitted the feedback
ONYX_BOT_FEEDBACK_VISIBILITY = (
    os.environ.get("ONYX_BOT_FEEDBACK_VISIBILITY") or "private"
)
# Should OnyxBot send an apology message if it's not able to find an answer
# That way the user isn't confused as to why OnyxBot reacted but then said nothing
# Off by default to be less intrusive (don't want to give a notif that just says we couldnt help)
NOTIFY_SLACKBOT_NO_ANSWER = (
    os.environ.get("NOTIFY_SLACKBOT_NO_ANSWER", "").lower() == "true"
)
# Mostly for debugging purposes but it's for explaining what went wrong
# if OnyxBot couldn't find an answer
ONYX_BOT_DISPLAY_ERROR_MSGS = os.environ.get(
    "ONYX_BOT_DISPLAY_ERROR_MSGS", ""
).lower() not in [
    "false",
    "",
]

# Maximum Questions Per Minute, Default Uncapped
ONYX_BOT_MAX_QPM = int(os.environ.get("ONYX_BOT_MAX_QPM") or 0) or None
# Maximum time to wait when a question is queued
ONYX_BOT_MAX_WAIT_TIME = int(os.environ.get("ONYX_BOT_MAX_WAIT_TIME") or 180)

# Time (in minutes) after which a Slack message is sent to the user to remind him to give feedback.
# Set to 0 to disable it (default)
ONYX_BOT_FEEDBACK_REMINDER = int(os.environ.get("ONYX_BOT_FEEDBACK_REMINDER") or 0)

# ONYX_BOT_RESPONSE_LIMIT_PER_TIME_PERIOD is the number of
# responses OnyxBot can send in a given time period.
# Set to 0 to disable the limit.
ONYX_BOT_RESPONSE_LIMIT_PER_TIME_PERIOD = int(
    os.environ.get("ONYX_BOT_RESPONSE_LIMIT_PER_TIME_PERIOD", "5000")
)
# ONYX_BOT_RESPONSE_LIMIT_TIME_PERIOD_SECONDS is the number
# of seconds until the response limit is reset.
ONYX_BOT_RESPONSE_LIMIT_TIME_PERIOD_SECONDS = int(
    os.environ.get("ONYX_BOT_RESPONSE_LIMIT_TIME_PERIOD_SECONDS", "86400")
)
