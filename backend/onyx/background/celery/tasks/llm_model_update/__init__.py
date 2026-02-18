"""Celery tasks for LLM model updates."""

from onyx.background.celery.tasks.llm_model_update.tasks import (  # noqa: F401
    check_for_auto_llm_updates,
)

__all__ = ["check_for_auto_llm_updates"]
