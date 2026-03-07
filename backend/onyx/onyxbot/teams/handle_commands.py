"""Teams bot command handlers (e.g., registration)."""

import asyncio

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.teams_bot import get_team_config_by_registration_key
from onyx.db.teams_bot import register_team
from onyx.onyxbot.constants import REGISTER_COMMAND
from onyx.onyxbot.exceptions import RegistrationError
from onyx.onyxbot.teams.cache import TeamsCacheManager
from onyx.onyxbot.teams.utils import extract_team_id
from onyx.onyxbot.teams.utils import extract_team_name
from onyx.onyxbot.teams.utils import strip_bot_mention
from onyx.server.manage.teams_bot.utils import parse_teams_registration_key
from onyx.utils.logger import setup_logger

logger = setup_logger()


async def handle_registration_command(
    text: str,
    activity_dict: dict,
    bot_name: str,
    cache: TeamsCacheManager,
) -> str:
    """Handle the 'register <key>' command.

    Returns a human-readable response message.
    """
    clean_text = strip_bot_mention(text, bot_name).strip()

    # Parse "register <key>"
    parts = clean_text.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != REGISTER_COMMAND:
        raise RegistrationError(
            f"Invalid registration command. Usage: @{bot_name} register <registration_key>"
        )

    registration_key = parts[1].strip()

    # Parse tenant_id from registration key
    tenant_id = parse_teams_registration_key(registration_key)
    if not tenant_id:
        raise RegistrationError("Invalid registration key format.")

    team_id = extract_team_id(activity_dict)
    team_name = extract_team_name(activity_dict) or "Unknown Team"

    if not team_id:
        raise RegistrationError(
            "Registration must be done from a Teams channel, not a DM."
        )

    def _register() -> str:
        with get_session_with_tenant(tenant_id=tenant_id) as db:
            # Lock the row to prevent concurrent registration with the same key
            config = get_team_config_by_registration_key(
                db, registration_key, for_update=True
            )
            if not config:
                raise RegistrationError("Registration key not found or already used.")

            if config.team_id is not None:
                raise RegistrationError("This registration key has already been used.")

            register_team(db, config, team_id, team_name)
            db.commit()
            return tenant_id

    registered_tenant_id = await asyncio.to_thread(_register)
    await cache.refresh_team(team_id, registered_tenant_id)

    logger.info(f"Team {team_id} ({team_name}) registered for tenant {tenant_id}")
    return f"Team **{team_name}** has been registered with Onyx. You can now configure channels in the admin panel."


def is_registration_command(text: str, bot_name: str) -> bool:
    """Check if a message is a registration command."""
    clean_text = strip_bot_mention(text, bot_name).strip()
    parts = clean_text.split(None, 1)
    return len(parts) >= 1 and parts[0].lower() == REGISTER_COMMAND
