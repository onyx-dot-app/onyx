from typing import NamedTuple

from pydantic import BaseModel
from pydantic import ConfigDict


class SkillBundleFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    size: int


class CustomSkillBundleContents(BaseModel):
    model_config = ConfigDict(frozen=True)

    instructions_markdown: str
    files: list[SkillBundleFile]


class GitHubRepository(NamedTuple):
    owner: str
    repo: str
    ref: str | None = None
    subpath: str | None = None


class GitHubSkillBundle(NamedTuple):
    path: str
    slug: str
    name: str
    description: str
    bundle_bytes: bytes | None
    unavailable_reason: str | None = None
