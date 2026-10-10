from pydantic import BaseModel


class NotionBotUser(BaseModel):
    workspace_id: str
    workspace_name: str
