from typing import Literal
from typing import Optional

from pydantic import BaseModel

from onyx.connectors.coda.models.common import CodaObjectType


class CodaWorkspaceReference(BaseModel):
    """Represents a Coda Workspace reference object"""

    id: str
    type: Literal[CodaObjectType.WORKSPACE]
    browserLink: str
    organizationId: Optional[str] = None
    name: Optional[str] = None
