from uuid import UUID

from pydantic import BaseModel


class PluginRename(BaseModel):
    plugin_id: UUID
    old_name: str
    new_name: str


class PrivatePluginsTransfer(BaseModel):
    plugin_ids: list[UUID]
    renames: list[PluginRename]
    affected_user_ids: set[UUID]
