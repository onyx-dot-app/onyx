from typing import Any
from typing import Literal
from typing import Optional

from onyx.connectors.coda.models.common import CodaObjectBase
from onyx.connectors.coda.models.common import CodaObjectType
from onyx.connectors.coda.models.page import CodaPageReference


class CodaControlReference(CodaObjectBase):
    """Represents a Coda Control reference object"""

    type: Literal[CodaObjectType.CONTROL]
    parent: Optional[CodaPageReference] = None


class CodaControl(CodaObjectBase):
    """Represents a Coda Control object"""

    type: Literal[CodaObjectType.CONTROL]
    values: dict[str, Any]
    parent: Optional[CodaPageReference] = None
