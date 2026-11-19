"""The tool options of an eval run keep the integrations that the default
agent uses for the eval user, each by the plugin that names it."""

from collections.abc import Collection
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from onyx.db.enums import PluginInstallationPolicy
from onyx.db.integration_access import UserIntegrationState
from onyx.db.models import Integration
from onyx.evals.eval import _tool_options
from onyx.tools.models import CapabilityEntry, PluginEntry


def test_eval_tool_options_keep_each_integration_the_user_turned_on() -> None:
    user_id = uuid4()
    plugins = {1: uuid4(), 2: uuid4()}

    def state(integration_id: int, turned_on: bool) -> UserIntegrationState:
        return UserIntegrationState(
            user_id=user_id,
            integration_id=integration_id,
            installation_policy=PluginInstallationPolicy.AVAILABLE,
            is_owner=False,
            for_everyone=True,
            choice=turned_on,
            turned_on=turned_on,
            integration_enabled=True,
        )

    def holders(
        _db_session: Session, integration_ids: Collection[int]
    ) -> list[tuple[UUID, Integration]]:
        return [
            (plugins[integration_id], Integration(id=integration_id))
            for integration_id in integration_ids
        ]

    with (
        patch(
            "onyx.integrations.policy.load_user_integration_states",
            return_value=[state(1, True), state(2, False)],
        ),
        patch("onyx.integrations.policy.list_integration_holders", holders),
    ):
        options = _tool_options(MagicMock(), user_id, [3], None)

    assert options.allowed == [
        CapabilityEntry(tool_id=3),
        PluginEntry(plugin_id=plugins[1]),
    ]
    assert options.allowed_plugins() == {plugins[1]: None}
