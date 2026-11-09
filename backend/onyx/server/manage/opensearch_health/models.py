from pydantic import BaseModel

from onyx.document_index.opensearch.models import ResourceHealth


class ResourcePopupResponse(BaseModel):
    show_popup: bool
    health: ResourceHealth
