"""Teams bot Activity handler using Bot Framework SDK."""

import asyncio

from botbuilder.core import ActivityHandler  # type: ignore[import-untyped]
from botbuilder.core import TurnContext
from botbuilder.schema import Activity  # type: ignore[import-untyped]
from botbuilder.schema import ActivityTypes
from botbuilder.schema import Attachment
from botbuilder.schema import ChannelAccount

from onyx.onyxbot.api_client import OnyxAPIClient
from onyx.onyxbot.constants import CACHE_REFRESH_INTERVAL
from onyx.onyxbot.exceptions import RegistrationError
from onyx.onyxbot.teams.cache import TeamsCacheManager
from onyx.onyxbot.teams.handle_commands import handle_registration_command
from onyx.onyxbot.teams.handle_commands import is_registration_command
from onyx.onyxbot.teams.handle_message import process_chat_message
from onyx.onyxbot.teams.handle_message import should_respond
from onyx.onyxbot.teams.utils import extract_channel_id
from onyx.onyxbot.teams.utils import extract_team_id
from onyx.server.query_and_chat.models import MessageOrigin
from onyx.utils.logger import setup_logger

logger = setup_logger()


class OnyxTeamsBot(ActivityHandler):
    """Activity handler for Teams bot.

    Handles incoming message activities, member additions, and routes
    messages to the appropriate handler (registration, chat).
    """

    def __init__(self) -> None:
        self.cache = TeamsCacheManager()
        self.api_client = OnyxAPIClient(origin=MessageOrigin.TEAMSBOT)
        self._cache_refresh_task: asyncio.Task[None] | None = None
        self._bot_id: str | None = None
        self._bot_name: str = "Onyx"

    async def initialize(self) -> None:
        """Initialize the bot: API client, cache, and background tasks."""
        await self.api_client.initialize()
        await self.cache.refresh_all()
        self._cache_refresh_task = asyncio.create_task(self._periodic_cache_refresh())
        logger.info("Teams bot initialized")

    async def shutdown(self) -> None:
        """Gracefully shut down the bot."""
        if self._cache_refresh_task:
            self._cache_refresh_task.cancel()
            try:
                await self._cache_refresh_task
            except asyncio.CancelledError:
                pass

        await self.api_client.close()
        self.cache.clear()
        logger.info("Teams bot shut down")

    async def _periodic_cache_refresh(self) -> None:
        """Background task to refresh cache periodically."""
        while True:
            await asyncio.sleep(CACHE_REFRESH_INTERVAL)
            try:
                await self.cache.refresh_all()
            except Exception as e:
                logger.error(f"Periodic cache refresh failed: {e}")

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        """Handle incoming message activities."""
        activity = turn_context.activity
        if not activity.text:
            return

        # Capture bot identity on first message
        if not self._bot_id and activity.recipient:
            self._bot_id = activity.recipient.id
            self._bot_name = activity.recipient.name or "Onyx"

        activity_dict = activity.as_dict() if hasattr(activity, "as_dict") else {}
        team_id = extract_team_id(activity_dict)
        channel_id = extract_channel_id(activity_dict)

        # Check for registration command
        if is_registration_command(activity.text, self._bot_name):
            await self._handle_registration(turn_context, activity_dict)
            return

        # Resolve tenant from team cache
        tenant_id: str | None = None
        if team_id:
            tenant_id = self.cache.get_tenant(team_id)
            if not tenant_id:
                logger.debug(f"No tenant found for team {team_id}")
                return
        else:
            # DM — not in a team context, so we can't determine tenant.
            # TODO(nik): support DM registration or default tenant lookup
            logger.debug("Ignoring DM (no team context to resolve tenant)")
            return

        # Check if bot should respond
        context = await asyncio.to_thread(
            should_respond,
            activity_dict,
            team_id,
            channel_id,
            tenant_id,
            self._bot_id or "",
        )

        if not context.should_respond:
            return

        api_key = self.cache.get_api_key(tenant_id)
        if not api_key:
            logger.warning(f"No API key for tenant {tenant_id}")
            return

        # Send typing indicator
        await turn_context.send_activity(Activity(type=ActivityTypes.typing))

        # Process message and send response
        card = await process_chat_message(
            text=activity.text,
            api_key=api_key,
            persona_id=context.persona_id,
            api_client=self.api_client,
            bot_name=self._bot_name,
        )

        # Send as Adaptive Card
        attachment = Attachment(
            content_type="application/vnd.microsoft.card.adaptive",
            content=card,
        )
        response = Activity(
            type=ActivityTypes.message,
            attachments=[attachment],
        )
        await turn_context.send_activity(response)

    async def _handle_registration(
        self,
        turn_context: TurnContext,
        activity_dict: dict,
    ) -> None:
        """Handle registration command."""
        try:
            result = await handle_registration_command(
                text=turn_context.activity.text or "",
                activity_dict=activity_dict,
                bot_name=self._bot_name,
                cache=self.cache,
            )
            await turn_context.send_activity(result)
        except RegistrationError as e:
            await turn_context.send_activity(f"Registration failed: {e}")
        except Exception as e:
            logger.exception(f"Registration error: {e}")
            await turn_context.send_activity(
                "An unexpected error occurred during registration."
            )

    async def on_members_added_activity(
        self,
        members_added: list[ChannelAccount],
        turn_context: TurnContext,
    ) -> None:
        """Handle when the bot is added to a team or conversation."""
        for member in members_added:
            # Only send welcome when the bot itself is added
            if member.id == turn_context.activity.recipient.id:
                from onyx.onyxbot.teams.cards import build_welcome_card

                attachment = Attachment(
                    content_type="application/vnd.microsoft.card.adaptive",
                    content=build_welcome_card(),
                )
                response = Activity(
                    type=ActivityTypes.message,
                    attachments=[attachment],
                )
                await turn_context.send_activity(response)
