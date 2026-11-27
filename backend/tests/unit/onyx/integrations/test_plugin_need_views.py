from onyx.integrations.models import PluginNeedState
from onyx.integrations.plugin_needs import need_views
from onyx.skills.models import PluginNeed


def test_a_saved_need_url_with_a_credential_is_not_shown() -> None:
    """A version saved before the fragment rule still holds the URL."""
    need = PluginNeed(
        name="svc", url="https://mcp.example.com/mcp#token=SECRET", transport="http"
    )

    [view] = need_views([need], [])

    assert (view.url, view.url_problem, view.state) == (
        None,
        "credential",
        PluginNeedState.NOT_SUPPORTED,
    )
