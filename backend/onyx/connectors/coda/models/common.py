from enum import StrEnum

from pydantic import BaseModel


class CodaObjectBase(BaseModel):
    id: str
    browserLink: str
    name: str
    href: str


class CodaObjectType(StrEnum):
    """
    Represents the allowed string values for object type.
    """

    DOC = "doc"
    PAGE = "page"
    TABLE = "table"
    COLUMN = "column"
    ROW = "row"
    FORMULA = "formula"
    CONTROL = "control"
    ICON = "icon"
    FOLDER = "folder"
    USER = "user"
    WORKSPACE = "workspace"
