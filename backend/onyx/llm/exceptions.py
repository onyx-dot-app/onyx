from pydantic import BaseModel


class LLMErrorInfo(BaseModel):
    message: str
    error_code: str
    is_retryable: bool


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
    """A model generation exceeded a transport or total request timeout."""


class LLMRateLimitError(Exception):
    """The provider rejected a request because its rate limit was reached."""


class LLMContextLimitError(Exception):
    """The generation input exceeds the selected model context limit."""
