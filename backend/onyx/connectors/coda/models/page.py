from enum import StrEnum
from typing import Literal
from typing import Optional

from pydantic import BaseModel

from onyx.connectors.coda.models.common import CodaObjectBase
from onyx.connectors.coda.models.common import CodaObjectType
from onyx.connectors.coda.models.icon import CodaIcon
from onyx.connectors.coda.models.person import CodaPersonValue


class CodaPageReference(CodaObjectBase):
    """Represents a Coda Page reference object"""

    type: Literal[CodaObjectType.PAGE]


class CodaPageContentType(StrEnum):
    """
    Represents the allowed string values for page content type.
    """

    CANVAS = "canvas"
    EMBED = "embed"
    SYNC_PAGE = "syncPage"


class CodaPageImage(BaseModel):
    """Represents the image of a Coda Page object"""

    browserLink: str
    type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class CodaPage(CodaObjectBase):
    """Represents a Coda Page object"""

    type: Literal[CodaObjectType.PAGE]
    isHidden: bool
    isEffectivelyHidden: bool
    children: list[CodaPageReference]
    contentType: CodaPageContentType
    subtitle: Optional[str] = None
    icon: Optional[CodaIcon] = None
    image: Optional[CodaPageImage] = None
    parent: Optional[CodaPageReference] = None
    author: Optional[CodaPersonValue] = None
    createdAt: Optional[str] = None
    createdBy: Optional[CodaPersonValue] = None
    updatedAt: Optional[str] = None
    updatedBy: Optional[CodaPersonValue] = None
