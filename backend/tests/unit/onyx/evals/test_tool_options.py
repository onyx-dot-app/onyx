"""The tool options of an eval run keep the plugins of the default agent."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from onyx.evals.eval import _tool_options
from onyx.tools.models import CapabilityEntry, PluginEntry


def test_eval_tool_options_keep_the_plugins_of_the_default_agent() -> None:
    plugin_id = uuid4()
    with patch(
        "onyx.evals.eval.list_persona_plugin_links",
        return_value=[MagicMock(plugin_id=plugin_id)],
    ):
        options = _tool_options(MagicMock(), [3], None)
    assert options.allowed == [
        CapabilityEntry(tool_id=3),
        PluginEntry(plugin_id=plugin_id),
    ]
    assert options.allowed_plugins() == {plugin_id: None}
