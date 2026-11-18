"""The tool options of an eval run keep the plugins that the default agent
uses for the eval user."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from onyx.evals.eval import _tool_options
from onyx.tools.models import CapabilityEntry, PluginEntry


def test_eval_tool_options_keep_each_plugin_the_user_runs() -> None:
    running = uuid4()
    turned_off = uuid4()
    states = [
        MagicMock(plugin_id=running, enabled=True, published=True),
        MagicMock(plugin_id=turned_off, enabled=False, published=True),
    ]
    with patch("onyx.integrations.policy.load_user_plugin_states", return_value=states):
        options = _tool_options(MagicMock(), uuid4(), [3], None)
    assert options.allowed == [
        CapabilityEntry(tool_id=3),
        PluginEntry(plugin_id=running),
    ]
    assert options.allowed_plugins() == {running: None}
