from onyx.connectors.coda.models.common import CodaObjectBase


class CodaIcon(CodaObjectBase):
    """Represents a Coda Doc object"""

    # MIME type of the icon
    type: str
    name: str
    browserLink: str
