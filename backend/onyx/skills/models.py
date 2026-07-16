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
