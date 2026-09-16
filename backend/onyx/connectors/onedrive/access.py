from onyx.access.models import ExternalAccess


def get_ce_onedrive_access() -> ExternalAccess:
    """CE has no external permission mapper, so access stays private."""
    return ExternalAccess.empty()
