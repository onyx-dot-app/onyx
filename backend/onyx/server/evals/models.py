from pydantic import BaseModel


class EvalRunResponse(BaseModel):
    """Response model for evaluation runs"""

    success: bool
