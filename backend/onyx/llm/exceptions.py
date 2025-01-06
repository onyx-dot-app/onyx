class GenAIDisabledException(Exception):
    def __init__(self, message: str = "Generative AI has been turned off") -> None:
        self.message = message
        super().__init__(self.message)
