from pydantic import BaseModel


class ConfluenceUser(BaseModel):
    user_id: str  # accountId in Cloud, userKey in Server
    username: str | None  # Confluence Cloud doesn't give usernames
    display_name: str
    # Confluence Data Center doesn't give email back by default,
    # have to fetch it with a different endpoint
    email: str | None
    type: str
