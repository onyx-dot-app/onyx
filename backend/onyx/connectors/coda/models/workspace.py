from typing import Literal
from typing import Optional

from onyx.connectors.coda.models.common import CodaObjectType


class CodaWorkspaceReference:
    """Represents a Coda Workspace reference object"""

    id: str
    type: Literal[CodaObjectType.WORKSPACE]
    browserLink: str
    organizationId: Optional[str]
    name: Optional[str]
