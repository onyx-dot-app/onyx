from pydantic import BaseModel


class CodaIcon(BaseModel):
    """Represents a Coda Doc object"""

    # MIME type of the icon
    type: str
    name: str
    browserLink: str
