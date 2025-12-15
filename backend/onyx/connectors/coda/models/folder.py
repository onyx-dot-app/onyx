from typing import Literal

from pydantic import BaseModel

from onyx.connectors.coda.models.common import CodaObjectType


class CodaFolderReference(BaseModel):
    """Represents a Coda Folder reference object"""

    id: str
    type: Literal[CodaObjectType.FOLDER]
    browserLink: str
    name: str
