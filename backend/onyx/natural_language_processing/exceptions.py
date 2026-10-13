class ModelServerRateLimitError(Exception):
    """
    Exception raised for rate limiting errors from the model server.
    """


class EmbeddingRequestFailedError(Exception):
    """
    Raised when a provider client already retried a request on its own and
    gave up. Callers must not retry the whole embedding call on top of it.
    """


class EmbeddingRequestRejectedError(EmbeddingRequestFailedError):
    """
    Raised when an embedding provider refuses the request itself, e.g. a model
    that does not support embeddings. The message is the provider's reason.
    """


class CohereBillingLimitError(Exception):
    """
    Raised when Cohere rejects requests because the billing cap is reached.
    """
