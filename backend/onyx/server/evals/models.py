from pydantic import BaseModel


class EvalRunAck(BaseModel):
    """Response model for evaluation runs"""

    success: bool
