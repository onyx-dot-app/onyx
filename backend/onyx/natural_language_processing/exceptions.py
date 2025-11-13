class ModelServerRateLimitError(Exception):
    """
    Exception raised for rate limiting errors from the model server.
    """


class CohereBillingLimitError(Exception):
    """
    Raised when Cohere rejects requests because the billing cap is reached.
    """
