from typing import Any
from typing import Literal
from typing import Optional

from onyx.connectors.coda.models.common import CodaObjectBase
from onyx.connectors.coda.models.common import CodaObjectType


class CodaDoc(CodaObjectBase):
    """Represents a Coda Doc object"""

    type: Literal[CodaObjectType.DOC]
    owner: str
    ownerName: str
    createdAt: str
    updatedAt: str
    icon: Optional[dict[str, Any]] = None
    docSize: Optional[dict[str, Any]] = None
    sourceDoc: Optional[dict[str, Any]] = None
    published: Optional[dict[str, Any]] = None
