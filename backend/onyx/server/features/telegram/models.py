from pydantic import BaseModel


class TelegramTokenSettings(BaseModel):
    token: str | None = None