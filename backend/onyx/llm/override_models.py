"""Overrides sent over the wire / stored in the DB

NOTE: these models are used in many places, so have to be
kepy in a separate file to avoid circular imports.
"""

from pydantic import BaseModel


class LLMOverride(BaseModel):
    """Per-request LLM settings that override persona defaults.

    All fields are optional — only the fields that differ from the persona's
    configured LLM need to be supplied. Used both over the wire (API requests)
    and for multi-model comparison, where one override is supplied per model.

    Attributes:
        model_provider: LLM provider slug (e.g. ``"openai"``, ``"anthropic"``).
            When ``None``, the persona's default provider is used.
        model_version: Specific model version string (e.g. ``"gpt-4o"``).
            When ``None``, the persona's default model is used.
        temperature: Sampling temperature in ``[0, 2]``. When ``None``, the
            persona's default temperature is used.
        display_name: Human-readable label shown in the UI for this model,
            e.g. ``"GPT-4 Turbo"``. Optional; falls back to ``model_version``
            when not set.
    """

    model_provider: str | None = None
    model_version: str | None = None
    temperature: float | None = None
    display_name: str | None = None

    # This disables the "model_" protected namespace for pydantic
    model_config = {"protected_namespaces": ()}


class PromptOverride(BaseModel):
    system_prompt: str | None = None
    task_prompt: str | None = None
