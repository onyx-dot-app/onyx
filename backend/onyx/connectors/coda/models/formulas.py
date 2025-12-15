from typing import Any
from typing import Literal
from typing import Optional

from onyx.connectors.coda.models.common import CodaObjectBase
from onyx.connectors.coda.models.common import CodaObjectType
from onyx.connectors.coda.models.page import CodaPageReference


class CodaFormulaReference(CodaObjectBase):
    """Represents a Coda Formula reference object"""

    type: Literal[CodaObjectType.FORMULA]
    parent: Optional[CodaPageReference] = None


class CodaFormula(CodaObjectBase):
    """Represents a Coda Formula object"""

    type: Literal[CodaObjectType.FORMULA]
    parent: Optional[CodaPageReference] = None
    values: dict[str, Any]
