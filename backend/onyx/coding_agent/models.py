from typing import Literal

from pydantic import BaseModel, Field


class CodingAgentCallResult(BaseModel):
    type: Literal["coding_result"] = "coding_result"
    answer: str


class CodingAgentArguments(BaseModel):
    query: str = Field(
        description="The user's question or task to perform against the repository."
    )
    github_repo: str = Field(
        description=(
            "GitHub repository URL or 'owner/repo' identifier (e.g. "
            "'https://github.com/onyx-dot-app/onyx' or 'onyx-dot-app/onyx')."
        )
    )
