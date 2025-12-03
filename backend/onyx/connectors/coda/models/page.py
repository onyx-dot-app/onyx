from enum import StrEnum
from typing import Any
from typing import Literal
from typing import Optional

from .common import CodaObjectBase
from onyx.connectors.coda.models.common import CodaObjectType


class CodaPageReference(CodaObjectBase):
    """Represents a Coda Page reference object"""


class CodaPageContentType(StrEnum):
    """
    Represents the allowed string values for page content type.
    """

    CANVAS = "canvas"
    EMBED = "embed"
    SYNC_PAGE = "syncPage"


class CodaPage(CodaObjectBase):
    """Represents a Coda Page object"""

    type: Literal[CodaObjectType.PAGE]
    subtitle: Optional[str] = None
    icon: Optional[dict[str, Any]] = None
    image: Optional[dict[str, Any]] = None
    contentType: CodaPageContentType
    isHidden: bool
    createdAt: str
    updatedAt: str
    parent: Optional[CodaPageReference] = None
    children: list[CodaPageReference]
