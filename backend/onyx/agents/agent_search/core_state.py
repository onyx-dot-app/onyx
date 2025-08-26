from operator import add
from typing import Annotated

from pydantic import BaseModel


class CoreState(BaseModel):
    """
    This is the core state that is shared across all subgraphs.
    """

    log_messages: Annotated[list[str], add] = []
    current_step_nr: int = 1


class SubgraphCoreState(BaseModel):
    """
    This is the core state that is shared across all subgraphs.
    """

    log_messages: Annotated[list[str], add] = []
