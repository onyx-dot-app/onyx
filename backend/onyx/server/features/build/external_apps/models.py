from pydantic import BaseModel, ConfigDict

from onyx.server.features.build.connect_app import ConnectAppDecision


class ConnectAppDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: ConnectAppDecision
