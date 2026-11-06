from typing import Any

from pydantic import BaseModel


class ChatSpace(BaseModel):
    # Resource name, spaces/{space}.
    name: str
    display_name: str
    uri: str | None = None

    @classmethod
    def from_api(cls, space: dict[str, Any]) -> "ChatSpace":
        name: str = space["name"]
        return cls(
            name=name,
            display_name=space.get("displayName") or name,
            uri=space.get("spaceUri"),
        )

    @property
    def space_id(self) -> str:
        return self.name.removeprefix("spaces/")


class ChatUser(BaseModel):
    email: str
    full_name: str | None = None
    suspended: bool = False

    @classmethod
    def from_directory(cls, user: dict[str, Any]) -> "ChatUser":
        return cls(
            email=user["primaryEmail"],
            full_name=(user.get("name") or {}).get("fullName"),
            suspended=bool(user.get("suspended")),
        )
