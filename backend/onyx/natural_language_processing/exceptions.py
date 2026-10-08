class ModelServerRateLimitError(Exception):
    """
    Exception raised for rate limiting errors from the model server.
    """


class EmbeddingRequestRejectedError(Exception):
    """
    Raised when an embedding provider refuses the request itself, e.g. a model
    that does not support embeddings. The message is the provider's reason.
    """


class CohereBillingLimitError(Exception):
    """
    Raised when Cohere rejects requests because the billing cap is reached.
    """
