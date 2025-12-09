from typing import Literal

from onyx.connectors.coda.models.common import CodaObjectBase
from onyx.connectors.coda.models.common import CodaObjectType
from onyx.connectors.coda.models.table.cell import CodaCellValue
from onyx.connectors.coda.models.table.table import CodaTableReference


class CodaRow(CodaObjectBase):
    """Represents a Coda Table Row"""

    type: Literal[CodaObjectType.ROW]
    index: int
    browserLink: str
    createdAt: str
    updatedAt: str
    values: dict[str, CodaCellValue]
    parent: CodaTableReference
