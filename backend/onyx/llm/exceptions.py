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


class InputBudgetExceededError(ClassifiedLLMError):
    def __init__(
        self,
        message: str = "Not enough tokens available for the required chat context.",
    ) -> None:
        super().__init__(
            client_error_msg=message,
            error_code="CONTEXT_TOO_LONG",
            is_retryable=False,
        )
