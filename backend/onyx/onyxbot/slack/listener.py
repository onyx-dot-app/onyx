import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from contextvars import Token
from threading import Event
from types import FrameType
from typing import Any
from typing import cast
from typing import Dict

import psycopg2.errors
from prometheus_client import Gauge
from prometheus_client import start_http_server
from redis.lock import Lock
from redis.lock import Lock as RedisLock
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry import ConnectionErrorRetryHandler
from slack_sdk.http_retry import RateLimitErrorRetryHandler
from slack_sdk.http_retry import RetryHandler
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from sqlalchemy.orm import Session

from onyx.chat.models import ThreadMessage
from onyx.configs.app_configs import DEV_MODE
from onyx.configs.app_configs import POD_NAME
from onyx.configs.app_configs import POD_NAMESPACE
from onyx.configs.constants import MessageType
from onyx.configs.constants import OnyxRedisLocks
from onyx.configs.onyxbot_configs import NOTIFY_SLACKBOT_NO_ANSWER
from onyx.configs.onyxbot_configs import ONYX_BOT_REPHRASE_MESSAGE
from onyx.configs.onyxbot_configs import ONYX_BOT_RESPOND_EVERY_CHANNEL
from onyx.connectors.slack.utils import expert_info_from_slack_id
from onyx.context.search.retrieval.search_runner import (
    download_nltk_data,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from onyx.db.models import SlackBot
from onyx.db.search_settings import get_current_search_settings
from onyx.db.slack_bot import fetch_slack_bot
from onyx.db.slack_bot import fetch_slack_bots
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.natural_language_processing.search_nlp_models import warm_up_bi_encoder
from onyx.onyxbot.slack.config import get_slack_channel_config_for_bot_and_channel
from onyx.onyxbot.slack.config import MAX_TENANTS_PER_POD
from onyx.onyxbot.slack.config import TENANT_ACQUISITION_INTERVAL
from onyx.onyxbot.slack.config import TENANT_HEARTBEAT_EXPIRATION
from onyx.onyxbot.slack.config import TENANT_HEARTBEAT_INTERVAL
from onyx.onyxbot.slack.config import TENANT_LOCK_EXPIRATION
from onyx.onyxbot.slack.constants import DISLIKE_BLOCK_ACTION_ID
from onyx.onyxbot.slack.constants import FEEDBACK_DOC_BUTTON_BLOCK_ACTION_ID
from onyx.onyxbot.slack.constants import FOLLOWUP_BUTTON_ACTION_ID
from onyx.onyxbot.slack.constants import FOLLOWUP_BUTTON_RESOLVED_ACTION_ID
from onyx.onyxbot.slack.constants import GENERATE_ANSWER_BUTTON_ACTION_ID
from onyx.onyxbot.slack.constants import IMMEDIATE_RESOLVED_BUTTON_ACTION_ID
from onyx.onyxbot.slack.constants import KEEP_TO_YOURSELF_ACTION_ID
from onyx.onyxbot.slack.constants import LIKE_BLOCK_ACTION_ID
from onyx.onyxbot.slack.constants import SHOW_EVERYONE_ACTION_ID
from onyx.onyxbot.slack.constants import VIEW_DOC_FEEDBACK_ID
from onyx.onyxbot.slack.handlers.handle_buttons import handle_doc_feedback_button
from onyx.onyxbot.slack.handlers.handle_buttons import handle_followup_button
from onyx.onyxbot.slack.handlers.handle_buttons import (
    handle_followup_resolved_button,
)
from onyx.onyxbot.slack.handlers.handle_buttons import (
    handle_generate_answer_button,
)
from onyx.onyxbot.slack.handlers.handle_buttons import (
    handle_publish_ephemeral_message_button,
)
from onyx.onyxbot.slack.handlers.handle_buttons import handle_slack_feedback
from onyx.onyxbot.slack.handlers.handle_message import handle_message
from onyx.onyxbot.slack.handlers.handle_message import (
    remove_scheduled_feedback_reminder,
)
from onyx.onyxbot.slack.handlers.handle_message import schedule_feedback_reminder
from onyx.onyxbot.slack.models import SlackContext
from onyx.onyxbot.slack.models import SlackMessageInfo
from onyx.onyxbot.slack.utils import check_message_limit
from onyx.onyxbot.slack.utils import decompose_action_id
from onyx.onyxbot.slack.utils import get_channel_name_from_id
from onyx.onyxbot.slack.utils import get_channel_type_from_id
from onyx.onyxbot.slack.utils import get_onyx_bot_auth_ids
from onyx.onyxbot.slack.utils import read_slack_thread
from onyx.onyxbot.slack.utils import remove_onyx_bot_tag
from onyx.onyxbot.slack.utils import rephrase_slack_message
from onyx.onyxbot.slack.utils import respond_in_thread_or_channel
from onyx.onyxbot.slack.utils import TenantSocketModeClient
from onyx.redis.redis_pool import get_redis_client
from onyx.server.manage.models import SlackBotTokens
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from onyx.utils.variable_functionality import set_is_ee_based_on_env_variable
from shared_configs.configs import DISALLOWED_SLACK_BOT_TENANT_LIST
from shared_configs.configs import MODEL_SERVER_HOST
from shared_configs.configs import MODEL_SERVER_PORT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.configs import SLACK_CHANNEL_ID
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# Prometheus metric for HPA
active_tenants_gauge = Gauge(
    "active_tenants",
    "Number of active tenants handled by this pod",
    ["namespace", "pod"],
)

# In rare cases, some users have been experiencing a massive amount of trivial messages coming through
# to the Slack Bot with trivial messages. Adding this to avoid exploding LLM costs while we track down
# the cause.
_SLACK_GREETINGS_TO_IGNORE = {
    "Welcome back!",
    "It's going to be a great day.",
    "Salutations!",
    "Greetings!",
    "Feeling great!",
    "Hi there",
    ":wave:",
}

# This is always (currently) the user id of Slack's official slackbot
_OFFICIAL_SLACKBOT_USER_ID = "USLACKBOT"

# Fields to exclude from Slack payload logging
# Intention is to not log slack message content
_EXCLUDED_SLACK_PAYLOAD_FIELDS = {"text", "blocks"}


class SlackbotHandler:
    def __init__(self) -> None:
        logger.info("Initializing SlackbotHandler")
        self.tenant_ids: set[str] = set()
        # The keys for these dictionaries are tuples of (tenant_id, slack_bot_id)
        self.socket_clients: Dict[tuple[str, int], TenantSocketModeClient] = {}
        self.slack_bot_tokens: Dict[tuple[str, int], SlackBotTokens] = {}

        # Store Redis lock objects here so we can release them properly
        self.redis_locks: Dict[str, Lock] = {}

        self.running = True
        self.pod_id = os.environ.get("HOSTNAME", "unknown_pod")
        self._shutdown_event = Event()

        self._lock = threading.Lock()

        logger.info(f"Pod ID: {self.pod_id}")

        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)
        logger.info("Signal handlers registered")

        # Start the Prometheus metrics server
        logger.info("Starting Prometheus metrics server")
        start_http_server(8000)
        logger.info("Prometheus metrics server started")

        # Start background threads
        logger.info("Starting background threads")
        self.acquire_thread = threading.Thread(
            target=self.acquire_tenants_loop, daemon=True
        )
        self.heartbeat_thread = threading.Thread(
            target=self.heartbeat_loop, daemon=True
        )

        self.acquire_thread.start()
        self.heartbeat_thread.start()

        logger.info("Background threads started")

    def acquire_tenants_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                self.acquire_tenants()

                # After we finish acquiring and managing Slack bots,
                # set the gauge to the number of active tenants (those with Slack bots).
                active_tenants_gauge.labels(namespace=POD_NAMESPACE, pod=POD_NAME).set(
                    len(self.tenant_ids)
                )
                logger.debug(
                    f"Current active tenants with Slack bots: {len(self.tenant_ids)}"
                )
            except Exception as e:
                logger.exception(f"Error in Slack acquisition: {e}")
            self._shutdown_event.wait(timeout=TENANT_ACQUISITION_INTERVAL)

    def heartbeat_loop(self) -> None:
        """This heartbeats into redis.

        NOTE(rkuo): this is not thread-safe with acquire_tenants_loop and will
        occasionally exception. Fix it!
        """
        while not self._shutdown_event.is_set():
            try:
                with self._lock:
                    tenant_ids = self.tenant_ids.copy()

                SlackbotHandler.send_heartbeats(self.pod_id, tenant_ids)
                logger.debug(f"Sent heartbeats for {len(tenant_ids)} active tenants")
            except Exception as e:
                logger.exception(f"Error in heartbeat loop: {e}")
            self._shutdown_event.wait(timeout=TENANT_HEARTBEAT_INTERVAL)

    def _manage_clients_per_tenant(
        self, db_session: Session, tenant_id: str, bot: SlackBot
    ) -> None:
        """
        - If the tokens are missing or empty, close the socket client and remove them.
        - If the tokens have changed, close the existing socket client and reconnect.
        - If the tokens are new, warm up the model and start a new socket client.
        """
        slack_bot_tokens = SlackBotTokens(
            bot_token=bot.bot_token,
            app_token=bot.app_token,
        )
        tenant_bot_pair = (tenant_id, bot.id)

        # If the tokens are missing or empty, close the socket client and remove them.
        if not slack_bot_tokens:
            logger.debug(
                f"No Slack bot tokens found for tenant={tenant_id}, bot {bot.id}"
            )
            if tenant_bot_pair in self.socket_clients:
                self.socket_clients[tenant_bot_pair].close()
                del self.socket_clients[tenant_bot_pair]
                del self.slack_bot_tokens[tenant_bot_pair]
            return

        tokens_exist = tenant_bot_pair in self.slack_bot_tokens
        tokens_changed = (
            tokens_exist and slack_bot_tokens != self.slack_bot_tokens[tenant_bot_pair]
        )
        if not tokens_exist or tokens_changed:
            if tokens_exist:
                logger.info(
                    f"Slack Bot tokens changed for tenant={tenant_id}, bot {bot.id}; reconnecting"
                )
            else:
                # Warm up the model if needed
                search_settings = get_current_search_settings(db_session)
                embedding_model = EmbeddingModel.from_db_model(
                    search_settings=search_settings,
                    server_host=MODEL_SERVER_HOST,
                    server_port=MODEL_SERVER_PORT,
                )
                warm_up_bi_encoder(embedding_model=embedding_model)

            self.slack_bot_tokens[tenant_bot_pair] = slack_bot_tokens

            # Close any existing connection first
            if tenant_bot_pair in self.socket_clients:
                self.socket_clients[tenant_bot_pair].close()

            socket_client = self.start_socket_client(
                bot.id, tenant_id, slack_bot_tokens
            )
            if socket_client:
                # Ensure tenant is tracked as active
                self.socket_clients[tenant_id, bot.id] = socket_client

                logger.info(
                    f"Started SocketModeClient: {tenant_id=} {socket_client.bot_name=} {bot.id=}"
                )

            self.tenant_ids.add(tenant_id)

    def acquire_tenants(self) -> None:
        """
        - Attempt to acquire a Redis lock for each tenant.
        - If acquired, check if that tenant actually has Slack bots.
        - If yes, store them in self.tenant_ids and manage the socket connections.
        - If a tenant in self.tenant_ids no longer has Slack bots, remove it (and release the lock in this scope).
        """

        token: Token[str | None]

        # tenants that are disabled (e.g. their trial is over and haven't subscribed)
        # for non-cloud, this will return an empty set
        gated_tenants = fetch_ee_implementation_or_noop(
            "onyx.server.tenants.product_gating",
            "get_gated_tenants",
            set(),
        )()
        all_active_tenants = [
            tenant_id
            for tenant_id in get_all_tenant_ids()
            if tenant_id not in gated_tenants
        ]

        # 1) Try to acquire locks for new tenants
        for tenant_id in all_active_tenants:
            if (
                DISALLOWED_SLACK_BOT_TENANT_LIST is not None
                and tenant_id in DISALLOWED_SLACK_BOT_TENANT_LIST
            ):
                logger.debug(f"Tenant {tenant_id} is disallowed; skipping.")
                continue

            # Already acquired in a previous loop iteration?
            if tenant_id in self.tenant_ids:
                continue

            # Respect max tenant limit per pod
            if len(self.tenant_ids) >= MAX_TENANTS_PER_POD:
                logger.info(
                    f"Max tenants per pod reached, not acquiring more: {MAX_TENANTS_PER_POD=}"
                )
                break

            redis_client = get_redis_client(tenant_id=tenant_id)
            # Acquire a Redis lock (non-blocking)
            # thread_local=False because the shutdown event is handled
            # on an arbitrary thread
            rlock: RedisLock = redis_client.lock(
                OnyxRedisLocks.SLACK_BOT_LOCK,
                timeout=TENANT_LOCK_EXPIRATION,
                thread_local=False,
            )
            lock_acquired = rlock.acquire(blocking=False)

            if not lock_acquired and not DEV_MODE:
                logger.debug(
                    f"Another pod holds the lock for tenant {tenant_id}, skipping."
                )
                continue

            if lock_acquired:
                logger.debug(f"Acquired lock for tenant {tenant_id}.")
                self.redis_locks[tenant_id] = rlock
            else:
                # DEV_MODE will skip the lock acquisition guard
                logger.debug(
                    f"Running in DEV_MODE. Not enforcing lock for {tenant_id}."
                )

            # Now check if this tenant actually has Slack bots
            token = CURRENT_TENANT_ID_CONTEXTVAR.set(
                tenant_id or POSTGRES_DEFAULT_SCHEMA
            )
            try:
                with get_session_with_tenant(tenant_id=tenant_id) as db_session:
                    bots: list[SlackBot] = []
                    try:
                        bots = list(fetch_slack_bots(db_session=db_session))
                    except KvKeyNotFoundError:
                        # No Slackbot tokens, pass
                        pass
                    except psycopg2.errors.UndefinedTable:
                        logger.error(
                            "Undefined table error in fetch_slack_bots. Tenant schema may need fixing."
                        )
                    except Exception as e:
                        logger.exception(
                            f"Error fetching Slack bots for tenant {tenant_id}: {e}"
                        )

                    if bots:
                        # Mark as active tenant
                        self.tenant_ids.add(tenant_id)
                        for bot in bots:
                            self._manage_clients_per_tenant(
                                db_session=db_session,
                                tenant_id=tenant_id,
                                bot=bot,
                            )
                    else:
                        # If no Slack bots, release lock immediately (unless in DEV_MODE)
                        if lock_acquired and not DEV_MODE:
                            rlock.release()
                            del self.redis_locks[tenant_id]
                        logger.debug(
                            f"No Slack bots for tenant {tenant_id}; lock released (if held)."
                        )
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

        # 2) Make sure tenants we're handling still have Slack bots
        for tenant_id in list(self.tenant_ids):
            token = CURRENT_TENANT_ID_CONTEXTVAR.set(
                tenant_id or POSTGRES_DEFAULT_SCHEMA
            )
            redis_client = get_redis_client(tenant_id=tenant_id)

            try:
                with get_session_with_current_tenant() as db_session:
                    # Attempt to fetch Slack bots
                    try:
                        bots = list(fetch_slack_bots(db_session=db_session))
                    except KvKeyNotFoundError:
                        # No Slackbot tokens, pass (and remove below)
                        bots = []
                    except Exception as e:
                        logger.exception(f"Error handling tenant {tenant_id}: {e}")
                        bots = []

                    if not bots:
                        logger.info(
                            f"Tenant {tenant_id} no longer has Slack bots. Removing."
                        )
                        self._remove_tenant(tenant_id)

                        # NOTE: We release the lock here (in the same scope it was acquired)
                        if tenant_id in self.redis_locks and not DEV_MODE:
                            try:
                                self.redis_locks[tenant_id].release()
                                del self.redis_locks[tenant_id]
                                logger.info(f"Released lock for tenant {tenant_id}")
                            except Exception as e:
                                logger.error(
                                    f"Error releasing lock for tenant {tenant_id}: {e}"
                                )
                    else:
                        # Manage or reconnect Slack bot sockets
                        for bot in bots:
                            self._manage_clients_per_tenant(
                                db_session=db_session,
                                tenant_id=tenant_id,
                                bot=bot,
                            )
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    def _remove_tenant(self, tenant_id: str) -> None:
        """
        Helper to remove a tenant from `self.tenant_ids` and close any socket clients.
        (Lock release now happens in `acquire_tenants()`, not here.)
        """
        socket_client_list = list(self.socket_clients.items())
        # Close all socket clients for this tenant
        for (t_id, slack_bot_id), client in socket_client_list:
            if t_id == tenant_id:
                client.close()
                del self.socket_clients[(t_id, slack_bot_id)]
                del self.slack_bot_tokens[(t_id, slack_bot_id)]
                logger.info(
                    f"Stopped SocketModeClient for tenant: {t_id}, app: {slack_bot_id}"
                )

        # Remove from active set
        if tenant_id in self.tenant_ids:
            self.tenant_ids.remove(tenant_id)

    @staticmethod
    def send_heartbeats(pod_id: str, tenant_ids: set[str]) -> None:
        current_time = int(time.time())
        logger.debug(f"Sending heartbeats for {len(tenant_ids)} active tenants")
        for tenant_id in tenant_ids:
            redis_client = get_redis_client(tenant_id=tenant_id)
            heartbeat_key = f"{OnyxRedisLocks.SLACK_BOT_HEARTBEAT_PREFIX}:{pod_id}"
            redis_client.set(
                heartbeat_key, current_time, ex=TENANT_HEARTBEAT_EXPIRATION
            )

    @staticmethod
    def start_socket_client(
        slack_bot_id: int, tenant_id: str, slack_bot_tokens: SlackBotTokens
    ) -> TenantSocketModeClient | None:
        """Returns the socket client if this succeeds"""
        socket_client: TenantSocketModeClient = _get_socket_client(
            slack_bot_tokens, tenant_id, slack_bot_id
        )

        try:
            bot_info = socket_client.web_client.auth_test()

            if bot_info["ok"]:
                bot_user_id = bot_info["user_id"]
                user_info = socket_client.web_client.users_info(user=bot_user_id)
                if user_info["ok"]:
                    bot_name = (
                        user_info["user"]["real_name"] or user_info["user"]["name"]
                    )
                    socket_client.bot_name = bot_name
                    # logger.info(
                    #     f"Started socket client for Slackbot with name '{bot_name}' (tenant: {tenant_id}, app: {slack_bot_id})"
                    # )
        except SlackApiError as e:
            # Only error out if we get a not_authed error
            if "not_authed" in str(e):
                # for some reason we want to add the tenant to the list when this happens?
                logger.error(
                    f"Authentication error - Invalid or expired credentials: "
                    f"{tenant_id=} {slack_bot_id=}. "
                    f"Error: {e}"
                )
                return None

            # Log other Slack API errors but continue
            logger.error(
                f"Slack API error fetching bot info: {e} for tenant: {tenant_id}, app: {slack_bot_id}"
            )
        except Exception as e:
            # Log other exceptions but continue
            logger.error(
                f"Error fetching bot info: {e} for tenant: {tenant_id}, app: {slack_bot_id}"
            )

        # Append the event handler
        process_slack_event = create_process_slack_event()
        socket_client.socket_mode_request_listeners.append(process_slack_event)  # type: ignore

        # Establish a WebSocket connection to the Socket Mode servers
        # logger.debug(
        #     f"Connecting socket client for tenant: {tenant_id}, app: {slack_bot_id}"
        # )
        socket_client.connect()
        # logger.info(
        #     f"Started SocketModeClient for tenant: {tenant_id}, app: {slack_bot_id}"
        # )

        return socket_client

    @staticmethod
    def stop_socket_clients(
        pod_id: str, socket_clients: Dict[tuple[str, int], TenantSocketModeClient]
    ) -> None:
        socket_client_list = list(socket_clients.items())
        length = len(socket_client_list)

        x = 0
        for (tenant_id, slack_bot_id), client in socket_client_list:
            x += 1
            client.close()
            logger.info(
                f"Stopped SocketModeClient {x}/{length}: "
                f"{pod_id=} {tenant_id=} {slack_bot_id=}"
            )

    def shutdown(self, signum: int | None, frame: FrameType | None) -> None:
        if not self.running:
            return

        logger.info("Shutting down gracefully")
        self.running = False
        self._shutdown_event.set()  # set the shutdown event

        # wait for threads to detect the event and exit
        self.acquire_thread.join(timeout=60.0)
        self.heartbeat_thread.join(timeout=60.0)

        # Stop all socket clients
        logger.info(f"Stopping {len(self.socket_clients)} socket clients")
        SlackbotHandler.stop_socket_clients(self.pod_id, self.socket_clients)

        # Release locks for all tenants we currently hold
        logger.info(f"Releasing locks for {len(self.tenant_ids)} tenants")
        for tenant_id in list(self.tenant_ids):
            if tenant_id in self.redis_locks:
                try:
                    self.redis_locks[tenant_id].release()
                    logger.info(f"Released lock for tenant {tenant_id}")
                except Exception as e:
                    logger.error(f"Error releasing lock for tenant {tenant_id}: {e}")
                finally:
                    del self.redis_locks[tenant_id]

        # Wait for background threads to finish (with a timeout)
        logger.info("Waiting for background threads to finish...")
        self.acquire_thread.join(timeout=5)
        self.heartbeat_thread.join(timeout=5)

        logger.info("Shutdown complete")
        sys.exit(0)


def sanitize_slack_payload(payload: dict) -> dict:
    """Remove message content from Slack payload for logging"""
    sanitized = {
        k: v for k, v in payload.items() if k not in _EXCLUDED_SLACK_PAYLOAD_FIELDS
    }
    if "event" in sanitized and isinstance(sanitized["event"], dict):
        sanitized["event"] = {
            k: v
            for k, v in sanitized["event"].items()
            if k not in _EXCLUDED_SLACK_PAYLOAD_FIELDS
        }
    return sanitized


def prefilter_requests(req: SocketModeRequest, client: TenantSocketModeClient) -> bool:
    """True to keep going, False to ignore this Slack request"""

    # skip cases where the bot is disabled in the web UI
    tenant_id = get_current_tenant_id()

    bot_token_user_id, bot_token_bot_id = get_onyx_bot_auth_ids(
        tenant_id, client.web_client
    )
    logger.info(f"prefilter_requests: {bot_token_user_id=} {bot_token_bot_id=}")

    with get_session_with_current_tenant() as db_session:
        slack_bot = fetch_slack_bot(
            db_session=db_session, slack_bot_id=client.slack_bot_id
        )
        if not slack_bot:
            logger.error(
                f"Slack bot with ID '{client.slack_bot_id}' not found. Skipping request."
            )
            return False

        if not slack_bot.enabled:
            logger.info(
                f"Slack bot with ID '{client.slack_bot_id}' is disabled. Skipping request."
            )
            return False

    if req.type == "events_api":
        # Verify channel is valid
        event = cast(dict[str, Any], req.payload.get("event", {}))
        msg = cast(str | None, event.get("text"))
        channel = cast(str | None, event.get("channel"))
        channel_specific_logger = setup_logger(extra={SLACK_CHANNEL_ID: channel})

        # This should never happen, but we can't continue without a channel since
        # we can't send a response without it
        if not channel:
            channel_specific_logger.warning("Found message without channel - skipping")
            return False

        if not msg:
            channel_specific_logger.warning(
                "Cannot respond to empty message - skipping"
            )
            return False

        if (
            req.payload.setdefault("event", {}).get("user", "")
            == _OFFICIAL_SLACKBOT_USER_ID
        ):
            channel_specific_logger.info(
                "Ignoring messages from Slack's official Slackbot"
            )
            return False

        if (
            msg in _SLACK_GREETINGS_TO_IGNORE
            or remove_onyx_bot_tag(tenant_id, msg, client=client.web_client)
            in _SLACK_GREETINGS_TO_IGNORE
        ):
            channel_specific_logger.error(
                f"Ignoring weird Slack greeting message: '{msg}'"
            )
            channel_specific_logger.error(
                f"Weird Slack greeting message payload: '{req.payload}'"
            )
            return False

        # Ensure that the message is a new message of expected type
        event_type = event.get("type")
        event.get("channel_type")

        if event_type not in ["app_mention", "message"]:
            return False

        bot_token_user_id, bot_token_bot_id = get_onyx_bot_auth_ids(
            tenant_id, client.web_client
        )
        if event_type == "message":
            is_onyx_bot_msg = False
            is_tagged = False

            event_user = event.get("user", "")
            event_bot_id = event.get("bot_id", "")

            # temporary debugging
            if tenant_id == "tenant_i-04224818da13bf695":
                logger.warning(
                    f"{tenant_id=} "
                    f"{bot_token_user_id=} "
                    f"{bot_token_bot_id=} "
                    f"{event=}"
                )

            is_dm = event.get("channel_type") == "im"
            if bot_token_user_id and f"<@{bot_token_user_id}>" in msg:
                is_tagged = True

            if bot_token_user_id and bot_token_user_id in event_user:
                is_onyx_bot_msg = True

            if bot_token_bot_id and bot_token_bot_id in event_bot_id:
                is_onyx_bot_msg = True

            # OnyxBot should never respond to itself
            if is_onyx_bot_msg:
                logger.info("Ignoring message from OnyxBot (self-message)")
                return False

            # DMs with the bot don't pick up the @OnyxBot so we have to keep the
            # caught events_api
            if is_tagged and not is_dm:
                # Let the tag flow handle this case, don't reply twice
                return False

        # Check if this is a bot message (either via bot_profile or bot_message subtype)
        is_bot_message = bool(
            event.get("bot_profile") or event.get("subtype") == "bot_message"
        )
        if is_bot_message:
            channel_name, _ = get_channel_name_from_id(
                client=client.web_client, channel_id=channel
            )
            with get_session_with_current_tenant() as db_session:
                slack_channel_config = get_slack_channel_config_for_bot_and_channel(
                    db_session=db_session,
                    slack_bot_id=client.slack_bot_id,
                    channel_name=channel_name,
                )

            # If OnyxBot is not specifically tagged and the channel is not set to respond to bots, ignore the message
            if (not bot_token_user_id or bot_token_user_id not in msg) and (
                not slack_channel_config
                or not slack_channel_config.channel_config.get("respond_to_bots")
            ):
                channel_specific_logger.info(
                    "Ignoring message from bot since respond_to_bots is disabled"
                )
                return False

        # Ignore things like channel_join, channel_leave, etc.
        # NOTE: "file_share" is just a message with a file attachment, so we
        # should not ignore it
        message_subtype = event.get("subtype")
        if message_subtype not in [None, "file_share", "bot_message"]:
            channel_specific_logger.info(
                f"Ignoring message with subtype '{message_subtype}' since it is a special message type"
            )
            return False

        message_ts = event.get("ts")
        thread_ts = event.get("thread_ts")
        # Pick the root of the thread (if a thread exists)
        # Can respond in thread if it's an "im" directly to Onyx or @OnyxBot is tagged
        if (
            thread_ts
            and message_ts != thread_ts
            and event_type != "app_mention"
            and event.get("channel_type") != "im"
        ):
            channel_specific_logger.debug(
                "Skipping message since it is not the root of a thread"
            )
            return False

        msg = cast(str, event.get("text", ""))
        if not msg:
            channel_specific_logger.error("Unable to process empty message")
            return False

    if req.type == "slash_commands":
        # Verify that there's an associated channel
        channel = req.payload.get("channel_id")
        channel_specific_logger = setup_logger(extra={SLACK_CHANNEL_ID: channel})

        if not channel:
            channel_specific_logger.error(
                "Received OnyxBot command without channel - skipping"
            )
            return False

        sender = req.payload.get("user_id")
        if not sender:
            channel_specific_logger.error(
                "Cannot respond to OnyxBot command without sender to respond to."
            )
            return False

    if not check_message_limit():
        return False

    # Don't log Slack message content
    logger.debug(
        f"Handling Slack request: {client.bot_name=} '{sanitize_slack_payload(req.payload)=}'"
    )
    return True


def process_feedback(req: SocketModeRequest, client: TenantSocketModeClient) -> None:
    if actions := req.payload.get("actions"):
        action = cast(dict[str, Any], actions[0])
        feedback_type = cast(str, action.get("action_id"))
        feedback_msg_reminder = cast(str, action.get("value"))
        feedback_id = cast(str, action.get("block_id"))
        channel_id = cast(str, req.payload["container"]["channel_id"])
        thread_ts = cast(
            str,
            req.payload["container"].get("thread_ts")
            or req.payload["container"].get("message_ts"),
        )
    else:
        logger.error("Unable to process feedback. Action not found")
        return

    user_id = cast(str, req.payload["user"]["id"])

    handle_slack_feedback(
        feedback_id=feedback_id,
        feedback_type=feedback_type,
        feedback_msg_reminder=feedback_msg_reminder,
        client=client.web_client,
        user_id_to_post_confirmation=user_id,
        channel_id_to_post_confirmation=channel_id,
        thread_ts_to_post_confirmation=thread_ts,
    )

    query_event_id, _, _ = decompose_action_id(feedback_id)
    logger.info(f"Successfully handled QA feedback for event: {query_event_id}")


def build_request_details(
    req: SocketModeRequest, client: TenantSocketModeClient
) -> SlackMessageInfo:
    tagged: bool = False

    tenant_id = get_current_tenant_id()
    if req.type == "events_api":
        event = cast(dict[str, Any], req.payload["event"])
        msg = cast(str, event["text"])
        channel = cast(str, event["channel"])

        # Check for both app_mention events and messages containing bot tag
        bot_token_user_id, _ = get_onyx_bot_auth_ids(tenant_id, client.web_client)
        message_ts = event.get("ts")
        thread_ts = event.get("thread_ts")
        sender_id = event.get("user") or None
        expert_info = expert_info_from_slack_id(
            sender_id, client.web_client, user_cache={}
        )
        email = expert_info.email if expert_info else None

        msg = remove_onyx_bot_tag(tenant_id, msg, client=client.web_client)

        if ONYX_BOT_REPHRASE_MESSAGE:
            logger.info(f"Rephrasing Slack message. Original message: {msg}")
            try:
                msg = rephrase_slack_message(msg)
                logger.info(f"Rephrased message: {msg}")
            except Exception as e:
                logger.error(f"Error while trying to rephrase the Slack message: {e}")
        else:
            logger.info(f"Received Slack message: {msg}")

        event_type = event.get("type")
        if event_type == "app_mention":
            tagged = True

        if event_type == "message":
            if bot_token_user_id:
                if f"<@{bot_token_user_id}>" in msg:
                    tagged = True

        if tagged:
            logger.debug("User tagged OnyxBot")

        # Build Slack context for federated search
        # Get proper channel type from Slack API instead of relying on event.channel_type
        channel_type = get_channel_type_from_id(client.web_client, channel)

        slack_context = SlackContext(
            channel_type=channel_type,
            channel_id=channel,
            user_id=sender_id or "unknown",
        )
        logger.info(f"build_request_details: Capturing Slack context: {slack_context}")

        if thread_ts != message_ts and thread_ts is not None:
            thread_messages = read_slack_thread(
                tenant_id=tenant_id,
                channel=channel,
                thread=thread_ts,
                client=client.web_client,
            )
        else:
            sender_display_name = None
            if expert_info:
                sender_display_name = expert_info.display_name
                if sender_display_name is None:
                    sender_display_name = (
                        f"{expert_info.first_name} {expert_info.last_name}"
                        if expert_info.last_name
                        else expert_info.first_name
                    )
                if sender_display_name is None:
                    sender_display_name = expert_info.email
            thread_messages = [
                ThreadMessage(
                    message=msg, sender=sender_display_name, role=MessageType.USER
                )
            ]

        return SlackMessageInfo(
            thread_messages=thread_messages,
            channel_to_respond=channel,
            msg_to_respond=cast(str, message_ts or thread_ts),
            thread_to_respond=cast(str, thread_ts or message_ts),
            sender_id=sender_id,
            email=email,
            bypass_filters=tagged,
            is_slash_command=False,
            is_bot_dm=event.get("channel_type") == "im",
            slack_context=slack_context,  # Add Slack context for federated search
        )

    elif req.type == "slash_commands":
        channel = req.payload["channel_id"]
        channel_name = req.payload["channel_name"]
        msg = req.payload["text"]
        sender = req.payload["user_id"]
        expert_info = expert_info_from_slack_id(
            sender, client.web_client, user_cache={}
        )
        email = expert_info.email if expert_info else None

        # Get proper channel type for slash commands too
        channel_type = get_channel_type_from_id(client.web_client, channel)

        slack_context = SlackContext(
            channel_type=channel_type,
            channel_id=channel,
            user_id=sender,
        )
        logger.info(
            f"build_request_details: Capturing Slack context for slash command: {slack_context}"
        )

        single_msg = ThreadMessage(message=msg, sender=None, role=MessageType.USER)

        return SlackMessageInfo(
            thread_messages=[single_msg],
            channel_to_respond=channel,
            msg_to_respond=None,
            thread_to_respond=None,
            sender_id=sender,
            email=email,
            bypass_filters=True,
            is_slash_command=True,
            is_bot_dm=channel_name == "directmessage",
            slack_context=slack_context,  # Add Slack context for federated search
        )

    raise RuntimeError("Programming fault, this should never happen.")


def apologize_for_fail(
    details: SlackMessageInfo,
    client: TenantSocketModeClient,
) -> None:
    respond_in_thread_or_channel(
        client=client.web_client,
        channel=details.channel_to_respond,
        thread_ts=details.msg_to_respond,
        text="Sorry, we weren't able to find anything relevant :cold_sweat:",
    )


def process_message(
    req: SocketModeRequest,
    client: TenantSocketModeClient,
    respond_every_channel: bool = ONYX_BOT_RESPOND_EVERY_CHANNEL,
    notify_no_answer: bool = NOTIFY_SLACKBOT_NO_ANSWER,
) -> None:
    tenant_id = get_current_tenant_id()
    if req.type == "events_api":
        event = cast(dict[str, Any], req.payload["event"])
        event_type = event.get("type")
        logger.info(
            f"process_message start: {tenant_id=} {req.type=} {req.envelope_id=} "
            f"{event_type=}"
        )
    else:
        logger.info(
            f"process_message start: {tenant_id=} {req.type=} {req.envelope_id=}"
        )

    # Throw out requests that can't or shouldn't be handled
    if not prefilter_requests(req, client):
        logger.info(
            f"process_message prefiltered: {tenant_id=} {req.type=} {req.envelope_id=}"
        )
        return

    details = build_request_details(req, client)
    channel = details.channel_to_respond
    channel_name, is_dm = get_channel_name_from_id(
        client=client.web_client, channel_id=channel
    )

    with get_session_with_current_tenant() as db_session:
        slack_channel_config = get_slack_channel_config_for_bot_and_channel(
            db_session=db_session,
            slack_bot_id=client.slack_bot_id,
            channel_name=channel_name,
        )

        follow_up = bool(
            slack_channel_config.channel_config
            and slack_channel_config.channel_config.get("follow_up_tags") is not None
        )

        feedback_reminder_id = schedule_feedback_reminder(
            details=details, client=client.web_client, include_followup=follow_up
        )

        failed = handle_message(
            message_info=details,
            slack_channel_config=slack_channel_config,
            client=client.web_client,
            feedback_reminder_id=feedback_reminder_id,
        )

        if failed:
            if feedback_reminder_id:
                remove_scheduled_feedback_reminder(
                    client=client.web_client,
                    channel=details.sender_id,
                    msg_id=feedback_reminder_id,
                )
            # Skipping answering due to pre-filtering is not considered a failure
            if notify_no_answer:
                apologize_for_fail(details, client)

    logger.info(
        f"process_message finished: success={not failed} {tenant_id=} {req.type=} {req.envelope_id=}"
    )


def acknowledge_message(req: SocketModeRequest, client: TenantSocketModeClient) -> None:
    response = SocketModeResponse(envelope_id=req.envelope_id)
    client.send_socket_mode_response(response)


def action_routing(req: SocketModeRequest, client: TenantSocketModeClient) -> None:
    if actions := req.payload.get("actions"):
        action = cast(dict[str, Any], actions[0])

        if action["action_id"] in [DISLIKE_BLOCK_ACTION_ID, LIKE_BLOCK_ACTION_ID]:
            # AI Answer feedback
            return process_feedback(req, client)
        elif action["action_id"] in [
            SHOW_EVERYONE_ACTION_ID,
            KEEP_TO_YOURSELF_ACTION_ID,
        ]:
            # Publish ephemeral message or keep hidden in main channel
            return handle_publish_ephemeral_message_button(
                req, client, action["action_id"]
            )
        elif action["action_id"] == FEEDBACK_DOC_BUTTON_BLOCK_ACTION_ID:
            # Activation of the "source feedback" button
            return handle_doc_feedback_button(req, client)
        elif action["action_id"] == FOLLOWUP_BUTTON_ACTION_ID:
            return handle_followup_button(req, client)
        elif action["action_id"] == IMMEDIATE_RESOLVED_BUTTON_ACTION_ID:
            return handle_followup_resolved_button(req, client, immediate=True)
        elif action["action_id"] == FOLLOWUP_BUTTON_RESOLVED_ACTION_ID:
            return handle_followup_resolved_button(req, client, immediate=False)
        elif action["action_id"] == GENERATE_ANSWER_BUTTON_ACTION_ID:
            return handle_generate_answer_button(req, client)


def view_routing(req: SocketModeRequest, client: TenantSocketModeClient) -> None:
    if view := req.payload.get("view"):
        if view["callback_id"] == VIEW_DOC_FEEDBACK_ID:
            return process_feedback(req, client)


def create_process_slack_event() -> (
    Callable[[TenantSocketModeClient, SocketModeRequest], None]
):
    def process_slack_event(
        client: TenantSocketModeClient, req: SocketModeRequest
    ) -> None:
        # Always respond right away, if Slack doesn't receive these frequently enough
        # it will assume the Bot is DEAD!!! :(
        acknowledge_message(req, client)

        try:
            if req.type == "interactive":
                if req.payload.get("type") == "block_actions":
                    return action_routing(req, client)
                elif req.payload.get("type") == "view_submission":
                    return view_routing(req, client)
            elif req.type == "events_api" or req.type == "slash_commands":
                return process_message(req, client)
        except Exception:
            logger.exception("Failed to process slack event")

    return process_slack_event


def _get_socket_client(
    slack_bot_tokens: SlackBotTokens, tenant_id: str, slack_bot_id: int
) -> TenantSocketModeClient:
    # For more info on how to set this up, checkout the docs:
    # https://docs.onyx.app/admin/getting_started/slack_bot_setup

    # use the retry handlers built into the slack sdk
    connection_error_retry_handler = ConnectionErrorRetryHandler()
    rate_limit_error_retry_handler = RateLimitErrorRetryHandler(max_retry_count=7)
    slack_retry_handlers: list[RetryHandler] = [
        connection_error_retry_handler,
        rate_limit_error_retry_handler,
    ]

    return TenantSocketModeClient(
        # This app-level token will be used only for establishing a connection
        app_token=slack_bot_tokens.app_token,
        web_client=WebClient(
            token=slack_bot_tokens.bot_token, retry_handlers=slack_retry_handlers
        ),
        tenant_id=tenant_id,
        slack_bot_id=slack_bot_id,
    )


if __name__ == "__main__":
    # Initialize the SqlEngine
    SqlEngine.init_engine(pool_size=20, max_overflow=5)

    # Initialize the tenant handler which will manage tenant connections
    logger.info("Starting SlackbotHandler")
    tenant_handler = SlackbotHandler()

    set_is_ee_based_on_env_variable()

    logger.info("Verifying query preprocessing (NLTK) data is downloaded")
    download_nltk_data()

    try:
        # Keep the main thread alive
        while tenant_handler.running:
            time.sleep(1)

    except Exception:
        logger.exception("Fatal error in main thread")
        tenant_handler.shutdown(None, None)
