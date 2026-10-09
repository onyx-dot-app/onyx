from onyx.connectors.connector_config import ConnectorConfig


class MockConnectorConfig(ConnectorConfig):
    mock_server_host: str
    mock_server_port: int
