from onyx.connectors.connector_config import ConnectorConfig


class BraintrustConnectorConfig(ConnectorConfig):
    project_name: str | None = None
    experiment_row_lookback_days: int | None = None
