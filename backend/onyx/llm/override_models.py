"""Overrides sent over the wire / stored in the DB

NOTE: these models are used in many places, so have to be
kepy in a separate file to avoid circular imports.
"""

from pydantic import BaseModel


class LLMOverride(BaseModel):
    model_provider: str | None = None
    model_version: str | None = None
    temperature: float | None = None

    # This disables the "model_" protected namespace for pydantic
    model_config = {"protected_namespaces": ()}


class PromptOverride(BaseModel):
    system_prompt: str | None = None
    task_prompt: str | None = None
