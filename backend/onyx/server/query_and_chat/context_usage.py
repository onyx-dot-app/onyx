from pydantic import BaseModel


class ContextUsage(BaseModel):
    used_tokens: int  # provider prompt_tokens of the last turn, OR baseline for an empty chat
    max_input_tokens: int  # the producing model's context window
    is_baseline: bool = False  # True when used_tokens is the empty-chat estimate (no real turn yet)
