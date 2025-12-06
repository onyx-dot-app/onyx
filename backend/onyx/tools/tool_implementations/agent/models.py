from pydantic import BaseModel


class AgentToolOverrideKwargs(BaseModel):
    current_depth: int = 0
    parent_agent_ids: list[int] = []
    original_query: str = ""


class AgentInvocationConfig(BaseModel):
    pass_conversation_context: bool = True
    pass_files: bool = False
    max_tokens_to_child: int | None = None
    max_tokens_from_child: int | None = None
    invocation_instructions: str | None = None
