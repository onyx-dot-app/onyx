from enum import StrEnum
from typing import Literal
from typing import Optional

from pydantic import BaseModel

from onyx.connectors.coda.models.common import CodaObjectBase
from onyx.connectors.coda.models.common import CodaObjectType
from onyx.connectors.coda.models.folder import CodaFolderReference
from onyx.connectors.coda.models.icon import CodaIcon
from onyx.connectors.coda.models.workspace import CodaWorkspaceReference


class CodaDocSize(BaseModel):
    """Represents the size of a Coda Doc object"""

    totalRowCount: int
    tableAndViewCount: int
    pageCount: int


class CodaDocSourceDoc(BaseModel):
    """Represents the source doc of a Coda Doc object"""

    id: str
    type: Literal[CodaObjectType.DOC]
    browserLink: str
    href: str


class CodaDocPublishedMode(StrEnum):
    """
    Represents the allowed string values for doc published mode.
    """

    VIEW = "view"
    PLAY = "play"
    EDIT = "edit"


class DocCategory(BaseModel):
    name: str


class CodaDocPublished(BaseModel):
    """Represents the published doc of a Coda Doc object"""

    browserLink: str
    discoverable: bool
    earnCredit: bool
    href: str
    mode: CodaDocPublishedMode
    category: list[DocCategory]
    description: str
    imageLink: str


class CodaDoc(CodaObjectBase):
    """Represents a Coda Doc object"""

    browserLink: str
    type: Literal[CodaObjectType.DOC]
    owner: str
    ownerName: str
    createdAt: str
    updatedAt: str
    workspace: CodaWorkspaceReference
    folder: CodaFolderReference
    icon: Optional[CodaIcon] = None
    docSize: Optional[CodaDocSize] = None
    sourceDoc: Optional[CodaDocSourceDoc] = None
    published: Optional[CodaDocPublished] = None
