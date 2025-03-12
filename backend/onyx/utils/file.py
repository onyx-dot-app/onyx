from pydantic import BaseModel


class OnyxFile(BaseModel):
    data: bytes
    mime_type: str
