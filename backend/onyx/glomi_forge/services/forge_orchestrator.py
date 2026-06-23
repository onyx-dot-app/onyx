"""State-machine driver for one Glomi Forge delivery session."""

import json
from datetime import datetime
from datetime import timezone
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.enums import GlomiForgeStatus
from onyx.db.glomi_forge import append_build_event
from onyx.db.glomi_forge import attach_builder
from onyx.db.glomi_forge import attach_sandbox
from onyx.db.glomi_forge import get_glomi_forge_session
from onyx.db.glomi_forge import set_failed
from onyx.db.glomi_forge import set_output
from onyx.db.glomi_forge import set_preview
from onyx.db.glomi_forge import update_status
from onyx.glomi_forge.interfaces.builder_adapter import BuilderAdapter
from onyx.glomi_forge.interfaces.sandbox_provider import SandboxProvider
from onyx.glomi_forge.schemas.builder import StartBuildInput
from onyx.glomi_forge.schemas.events import ArtifactReady
from onyx.glomi_forge.schemas.events import BuilderFailed
from onyx.glomi_forge.schemas.events import BuilderFinished
from onyx.glomi_forge.schemas.events import PreviewReady
from onyx.glomi_forge.schemas.forge_session import ForgeError
from onyx.glomi_forge.schemas.forge_spec import ForgeSpec
from onyx.glomi_forge.schemas.output_manifest import OutputManifest
from onyx.glomi_forge.schemas.sandbox import CreateSandboxInput
from onyx.glomi_forge.schemas.sandbox import SandboxFile
from onyx.glomi_forge.services.template_service import TemplateDescriptor
from onyx.glomi_forge.services.template_service import TemplateService
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class ForgeOrchestrator:
    def __init__(
        self,
        db_session: Session,
        provider: SandboxProvider,
        adapter: BuilderAdapter,
        template_service: TemplateService,
    ) -> None:
        self.db_session = db_session
        self.provider = provider
        self.adapter = adapter
        self.template_service = template_service

    def run(self, session_id: UUID) -> None:
        session = get_glomi_forge_session(self.db_session, session_id)
        if session is None:
            logger.error("glomi_forge session %s not found", session_id)
            return

        sandbox_id: str | None = None
        try:
            spec = ForgeSpec.model_validate(session.spec)
            template = self.template_service.resolve(session.artifact_type)
            update_status(
                self.db_session,
                session_id,
                GlomiForgeStatus.PROVISIONING,
            )
            create_result = self.provider.create_sandbox(
                CreateSandboxInput(
                    session_id=str(session_id),
                    snapshot=template.snapshot,
                    labels={"session_id": str(session_id)},
                )
            )
            sandbox_id = create_result.sandbox_id
            attach_sandbox(self.db_session, session_id, sandbox_id)

            self.provider.write_files(
                sandbox_id,
                self._context_files(spec=spec, template=template),
            )

            update_status(self.db_session, session_id, GlomiForgeStatus.BUILDING)
            start_result = self.adapter.start_build(
                StartBuildInput(
                    build_session_id=str(session_id),
                    sandbox_id=sandbox_id,
                )
            )
            attach_builder(
                self.db_session,
                session_id,
                start_result.builder_session_id,
            )

            for event in self.adapter.subscribe(start_result.builder_session_id):
                append_build_event(self.db_session, session_id, event)

                if isinstance(event, PreviewReady):
                    preview = self.provider.expose_preview(sandbox_id, event.port)
                    set_preview(self.db_session, session_id, preview)
                    update_status(
                        self.db_session,
                        session_id,
                        GlomiForgeStatus.PREVIEW_READY,
                    )
                elif isinstance(event, ArtifactReady):
                    raw_manifest = self.provider.read_file(
                        sandbox_id,
                        event.manifest_path,
                    )
                    set_output(
                        self.db_session,
                        session_id,
                        OutputManifest.model_validate_json(raw_manifest),
                    )
                elif isinstance(event, BuilderFinished):
                    update_status(
                        self.db_session,
                        session_id,
                        GlomiForgeStatus.COMPLETED,
                    )
                    return
                elif isinstance(event, BuilderFailed):
                    self._fail(session_id, event.error, sandbox_id)
                    return

            self._fail(
                session_id,
                "builder stream ended without completion",
                sandbox_id,
            )
        except Exception as e:
            logger.exception("glomi_forge session %s crashed", session_id)
            self._fail(session_id, str(e), sandbox_id)

    def _fail(
        self,
        session_id: UUID,
        message: str,
        sandbox_id: str | None,
    ) -> None:
        set_failed(
            self.db_session,
            session_id,
            ForgeError(
                code="FORGE_BUILDER_FAILED",
                message=message,
                occurred_at=_now(),
            ),
        )
        if sandbox_id is None:
            return

        try:
            self.provider.delete_sandbox(sandbox_id)
        except Exception:
            logger.exception("failed cleaning glomi_forge sandbox %s", sandbox_id)

    @staticmethod
    def _context_files(
        *,
        spec: ForgeSpec,
        template: TemplateDescriptor,
    ) -> list[SandboxFile]:
        task_json = {
            "template_id": template.template_id,
            "title": spec.title,
            "goal": spec.goal,
            "target_audience": spec.target_audience,
            "requirements": spec.requirements,
            "constraints": spec.constraints,
            "visual_style": spec.visual_style,
            "acceptance_criteria": spec.acceptance_criteria,
            "inputs": spec.inputs.model_dump(mode="json"),
            "outputs": spec.outputs.model_dump(mode="json"),
        }
        return [
            SandboxFile(
                path="/workspace/input/task.json",
                content=json.dumps(task_json, ensure_ascii=False),
            ),
            SandboxFile(
                path="/workspace/context/AGENTS.md",
                content=template.agents_md,
            ),
            SandboxFile(
                path="/workspace/context/SYSTEM.md",
                content=template.system_md,
            ),
            SandboxFile(
                path="/workspace/context/output_contract.md",
                content=template.output_contract,
            ),
        ]
