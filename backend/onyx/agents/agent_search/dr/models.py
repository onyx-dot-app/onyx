from pydantic import BaseModel

from onyx.agents.agent_search.dr.states import OrchestratorStep


class OrchestratorDecisons(BaseModel):
    reasoning: str
    next_step: OrchestratorStep
    plan_of_record: list[OrchestratorStep]
