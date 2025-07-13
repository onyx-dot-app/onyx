from enum import Enum

from pydantic import BaseModel


class DRPath(str, Enum):
    SEARCH = "SEARCH"
    KNOWLEDGE_GRAPH = "KNOWLEDGE_GRAPH"
    CLOSER = "CLOSER"


class OrchestratorStep(BaseModel):
    tool: DRPath
    questions: list[str]


class OrchestratorDecisons(BaseModel):
    reasoning: str
    next_step: OrchestratorStep
    plan_of_record: str


class OrchestratorDecisonsNoPlan(BaseModel):
    reasoning: str
    next_step: OrchestratorStep


class OrchestrationPlan(BaseModel):
    reasoning: str
    plan: str
