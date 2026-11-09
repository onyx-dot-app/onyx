from unittest.mock import patch

import pydantic
import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.web.config import WEB_CONNECTOR_VALID_SETTINGS, WebConnectorConfig
from onyx.connectors.web.connector import WebConnector


def test_upload_mode_raises_without_opening_file() -> None:
    with patch("builtins.open") as mock_open:
        with pytest.raises(ConnectorValidationError, match="no longer supported"):
            WebConnector(
                base_url="/etc/passwd",
                web_connector_type=WEB_CONNECTOR_VALID_SETTINGS.UPLOAD.value,
            )
    mock_open.assert_not_called()


def test_config_rejects_upload_mode() -> None:
    with pytest.raises(pydantic.ValidationError, match="no longer supported"):
        WebConnectorConfig.model_validate(
            {"base_url": "/etc/passwd", "web_connector_type": "upload"}
        )
