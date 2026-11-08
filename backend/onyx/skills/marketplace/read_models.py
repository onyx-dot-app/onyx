from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Result(BaseModel):
    model_config = ConfigDict(frozen=True)


class MarketplaceSkill(_Result):
    entry_key: str
    path: str


class ReadySkill(MarketplaceSkill):
    status: Literal["ok"] = "ok"
    bundle_bytes: bytes
    content_digest: str


class BlockedSkill(MarketplaceSkill):
    status: Literal["blocked"] = "blocked"
    reason: str


class UnsupportedPlugin(_Result):
    status: Literal["not_supported"] = "not_supported"
    entry_key: str
    reason: str


class CompleteMarketplace(_Result):
    status: Literal["complete"] = "complete"
    entries: tuple[ReadySkill | BlockedSkill | UnsupportedPlugin, ...]


class FailedMarketplace(_Result):
    status: Literal["failed"] = "failed"
    reason: str
