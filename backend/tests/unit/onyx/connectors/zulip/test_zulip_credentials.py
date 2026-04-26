from pathlib import Path
from unittest.mock import Mock

from onyx.connectors.zulip.connector import ZulipConnector


def test_load_credentials_uses_resolved_tempdir(monkeypatch, tmp_path: Path) -> None:
    """Regression coverage for environments where tempfile.tempdir is None."""

    client_mock = Mock()
    monkeypatch.setattr("onyx.connectors.zulip.connector.Client", client_mock)
    monkeypatch.setattr("onyx.connectors.zulip.connector.tempfile.tempdir", None)
    monkeypatch.setattr(
        "onyx.connectors.zulip.connector.tempfile.gettempdir", lambda: str(tmp_path)
    )

    connector = ZulipConnector(realm_name="acme", realm_url="zulip.example.com")
    connector.load_credentials(
        {
            "zuliprc_content": "[api] email=bot@example.com key=secret site=https://zulip.example.com"
        }
    )

    config_file = tmp_path / "zuliprc-acme"
    assert config_file.exists()
    assert "\n" in config_file.read_text()
    client_mock.assert_called_once_with(config_file=str(config_file))
