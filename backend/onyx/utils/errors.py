class EERequiredError(Exception):
    """This error is thrown if an Enterprise Edition feature or API is
    requested but the Enterprise Edition flag is not set."""
