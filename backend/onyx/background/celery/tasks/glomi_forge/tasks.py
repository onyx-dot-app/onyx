"""Celery task that drives a Glomi Forge session end-to-end."""

from uuid import UUID

from celery import shared_task
from celery import Task
from sqlalchemy.orm import Session

from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.glomi_forge.interfaces.builder_adapter import BuilderAdapter
from onyx.glomi_forge.interfaces.sandbox_provider import SandboxProvider
from onyx.glomi_forge.providers.builder.pi_builder_adapter import PiBuilderAdapter
from onyx.glomi_forge.providers.sandbox.daytona_provider import DaytonaSandboxProvider
from onyx.glomi_forge.services.forge_orchestrator import ForgeOrchestrator
from onyx.glomi_forge.services.template_service import TemplateService

BUILD_TIME_LIMIT_SECONDS = 3600


def _run(
    session_id: UUID,
    db_session: Session,
    provider: SandboxProvider,
    adapter: BuilderAdapter,
) -> None:
    ForgeOrchestrator(
        db_session,
        provider,
        adapter,
        TemplateService(),
    ).run(session_id)


@shared_task(
    name=OnyxCeleryTask.GLOMI_FORGE_RUN_SESSION,
    soft_time_limit=BUILD_TIME_LIMIT_SECONDS,
    bind=True,
    ignore_result=True,
)
def run_forge_session_task(self: Task, *, session_id: str, tenant_id: str) -> None:
    _ = self
    _ = tenant_id
    with get_session_with_current_tenant() as db_session:
        provider = DaytonaSandboxProvider()
        adapter = PiBuilderAdapter(provider)
        _run(UUID(session_id), db_session, provider, adapter)


def enqueue_forge_session(session_id: UUID, tenant_id: str) -> None:
    from onyx.background.celery.apps.primary import celery_app

    celery_app.send_task(
        OnyxCeleryTask.GLOMI_FORGE_RUN_SESSION,
        kwargs={"session_id": str(session_id), "tenant_id": tenant_id},
        expires=BUILD_TIME_LIMIT_SECONDS,
    )
