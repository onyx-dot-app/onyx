class ClassifiedLLMError(RuntimeError):
    def __init__(
        self,
        *,
        client_error_msg: str,
        error_code: str,
        is_retryable: bool,
    ) -> None:
        super().__init__(client_error_msg)
        self.client_error_msg = client_error_msg
        self.error_code = error_code
        self.is_retryable = is_retryable


class LLMTimeoutError(TimeoutError):
    """The provider did not complete within the request deadline."""


class LLMRateLimitError(Exception):
    """The provider rejected the request due to its rate limit."""
