from pydantic import BaseModel


class OrchestratorDecisons(BaseModel):
    reasoning: str
    next_step: dict[str, str]
    plan_of_record: str
