from typing import Literal

from onyx.connectors.coda.models.common import CodaObjectType


class CodaFolderReference:
    """Represents a Coda Folder reference object"""

    id: str
    type: Literal[CodaObjectType.FOLDER]
    browserLink: str
    name: str
