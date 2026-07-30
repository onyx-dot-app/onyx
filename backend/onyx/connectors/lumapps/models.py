from onyx.connectors.models import ConnectorCheckpoint


class LumAppsCheckpoint(ConnectorCheckpoint):
    # Within-run pagination only. LumApps content/list returns an opaque (offset-based)
    # `cursor` string; we resume from it within a single indexing run. Cross-run
    # incrementality is driven by the framework poll window (`start`), not this field,
    # because Onyx resets the checkpoint to a dummy after every successful run.
    cursor: str | None = None
