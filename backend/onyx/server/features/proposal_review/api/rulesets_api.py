"""API endpoints for rulesets and rules."""

from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.proposal_review.api.models import BulkRuleUpdateRequest
from onyx.server.features.proposal_review.api.models import BulkRuleUpdateResponse
from onyx.server.features.proposal_review.api.models import ImportResponse
from onyx.server.features.proposal_review.api.models import RuleCreate
from onyx.server.features.proposal_review.api.models import RuleResponse
from onyx.server.features.proposal_review.api.models import RulesetCreate
from onyx.server.features.proposal_review.api.models import RulesetResponse
from onyx.server.features.proposal_review.api.models import RulesetUpdate
from onyx.server.features.proposal_review.api.models import RuleUpdate
from onyx.server.features.proposal_review.configs import IMPORT_MAX_FILE_SIZE_BYTES
from onyx.server.features.proposal_review.db import rulesets as rulesets_db
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter()


# =============================================================================
# Rulesets
# =============================================================================


@router.get("/rulesets")
def list_rulesets(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),  # noqa: ARG001
    db_session: Session = Depends(get_session),
) -> list[RulesetResponse]:
    """List all rulesets for the current tenant."""
    tenant_id = get_current_tenant_id()
    rulesets = rulesets_db.list_rulesets(tenant_id, db_session)
    return [RulesetResponse.from_model(rs) for rs in rulesets]


@router.post("/rulesets", status_code=201)
def create_ruleset(
    request: RulesetCreate,
    user: User = Depends(require_permission(Permission.MANAGE_CONNECTORS)),
    db_session: Session = Depends(get_session),
) -> RulesetResponse:
    """Create a new ruleset."""
    tenant_id = get_current_tenant_id()
    ruleset = rulesets_db.create_ruleset(
        tenant_id=tenant_id,
        name=request.name,
        description=request.description,
        is_default=request.is_default,
        created_by=user.id,
        db_session=db_session,
    )
    db_session.commit()
    return RulesetResponse.from_model(ruleset, include_rules=False)


@router.get("/rulesets/{ruleset_id}")
def get_ruleset(
    ruleset_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),  # noqa: ARG001
    db_session: Session = Depends(get_session),
) -> RulesetResponse:
    """Get a ruleset with all its rules."""
    tenant_id = get_current_tenant_id()
    ruleset = rulesets_db.get_ruleset(ruleset_id, tenant_id, db_session)
    if not ruleset:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Ruleset not found")
    return RulesetResponse.from_model(ruleset)


@router.put("/rulesets/{ruleset_id}")
def update_ruleset(
    ruleset_id: UUID,
    request: RulesetUpdate,
    user: User = Depends(  # noqa: ARG001
        require_permission(Permission.MANAGE_CONNECTORS)
    ),
    db_session: Session = Depends(get_session),
) -> RulesetResponse:
    """Update a ruleset."""
    tenant_id = get_current_tenant_id()
    ruleset = rulesets_db.update_ruleset(
        ruleset_id=ruleset_id,
        tenant_id=tenant_id,
        name=request.name,
        description=request.description,
        is_default=request.is_default,
        is_active=request.is_active,
        db_session=db_session,
    )
    if not ruleset:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Ruleset not found")
    db_session.commit()
    return RulesetResponse.from_model(ruleset)


@router.delete("/rulesets/{ruleset_id}", status_code=204)
def delete_ruleset(
    ruleset_id: UUID,
    user: User = Depends(  # noqa: ARG001
        require_permission(Permission.MANAGE_CONNECTORS)
    ),
    db_session: Session = Depends(get_session),
) -> None:
    """Delete a ruleset and all its rules."""
    tenant_id = get_current_tenant_id()
    deleted = rulesets_db.delete_ruleset(ruleset_id, tenant_id, db_session)
    if not deleted:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Ruleset not found")
    db_session.commit()


# =============================================================================
# Rules
# =============================================================================


@router.post(
    "/rulesets/{ruleset_id}/rules",
    status_code=201,
)
def create_rule(
    ruleset_id: UUID,
    request: RuleCreate,
    user: User = Depends(  # noqa: ARG001
        require_permission(Permission.MANAGE_CONNECTORS)
    ),
    db_session: Session = Depends(get_session),
) -> RuleResponse:
    """Create a new rule within a ruleset."""
    # Verify ruleset exists and belongs to tenant
    tenant_id = get_current_tenant_id()
    ruleset = rulesets_db.get_ruleset(ruleset_id, tenant_id, db_session)
    if not ruleset:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Ruleset not found")

    rule = rulesets_db.create_rule(
        ruleset_id=ruleset_id,
        name=request.name,
        description=request.description,
        category=request.category,
        rule_type=request.rule_type,
        rule_intent=request.rule_intent,
        prompt_template=request.prompt_template,
        source=request.source,
        authority=request.authority,
        is_hard_stop=request.is_hard_stop,
        priority=request.priority,
        db_session=db_session,
    )
    db_session.commit()
    return RuleResponse.from_model(rule)


@router.put("/rules/{rule_id}")
def update_rule(
    rule_id: UUID,
    request: RuleUpdate,
    user: User = Depends(  # noqa: ARG001
        require_permission(Permission.MANAGE_CONNECTORS)
    ),
    db_session: Session = Depends(get_session),
) -> RuleResponse:
    """Update a rule."""
    # Verify the rule belongs to a ruleset owned by the current tenant
    tenant_id = get_current_tenant_id()
    rule = rulesets_db.get_rule(rule_id, db_session)
    if not rule:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Rule not found")
    ruleset = rulesets_db.get_ruleset(rule.ruleset_id, tenant_id, db_session)
    if not ruleset:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Rule not found")

    updated_rule = rulesets_db.update_rule(
        rule_id=rule_id,
        name=request.name,
        description=request.description,
        category=request.category,
        rule_type=request.rule_type,
        rule_intent=request.rule_intent,
        prompt_template=request.prompt_template,
        authority=request.authority,
        is_hard_stop=request.is_hard_stop,
        priority=request.priority,
        is_active=request.is_active,
        db_session=db_session,
    )
    if not updated_rule:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Rule not found")
    db_session.commit()
    return RuleResponse.from_model(updated_rule)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(
    rule_id: UUID,
    user: User = Depends(  # noqa: ARG001
        require_permission(Permission.MANAGE_CONNECTORS)
    ),
    db_session: Session = Depends(get_session),
) -> None:
    """Delete a rule."""
    # Verify the rule belongs to a ruleset owned by the current tenant
    tenant_id = get_current_tenant_id()
    rule = rulesets_db.get_rule(rule_id, db_session)
    if not rule:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Rule not found")
    ruleset = rulesets_db.get_ruleset(rule.ruleset_id, tenant_id, db_session)
    if not ruleset:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Rule not found")

    deleted = rulesets_db.delete_rule(rule_id, db_session)
    if not deleted:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Rule not found")
    db_session.commit()


@router.post(
    "/rulesets/{ruleset_id}/rules/bulk-update",
)
def bulk_update_rules(
    ruleset_id: UUID,
    request: BulkRuleUpdateRequest,
    user: User = Depends(  # noqa: ARG001
        require_permission(Permission.MANAGE_CONNECTORS)
    ),
    db_session: Session = Depends(get_session),
) -> BulkRuleUpdateResponse:
    """Batch activate/deactivate/delete rules."""
    # Verify the ruleset belongs to the current tenant
    tenant_id = get_current_tenant_id()
    ruleset = rulesets_db.get_ruleset(ruleset_id, tenant_id, db_session)
    if not ruleset:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Ruleset not found")

    if request.action not in ("activate", "deactivate", "delete"):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "action must be 'activate', 'deactivate', or 'delete'",
        )
    # Only operate on rules that belong to this ruleset (tenant-scoped)
    count = rulesets_db.bulk_update_rules(
        request.rule_ids, request.action, ruleset_id, db_session
    )
    db_session.commit()
    return BulkRuleUpdateResponse(updated_count=count)


@router.post(
    "/rulesets/{ruleset_id}/import",
)
def import_checklist(
    ruleset_id: UUID,
    file: UploadFile,
    user: User = Depends(  # noqa: ARG001
        require_permission(Permission.MANAGE_CONNECTORS)
    ),
    db_session: Session = Depends(get_session),
) -> ImportResponse:
    """Upload a checklist document and parse it into atomic review rules via LLM.

    Accepts a checklist file (.pdf, .docx, .xlsx, .txt), extracts its text,
    and uses LLM to decompose it into atomic, self-contained rules.
    Rules are saved to the ruleset as inactive drafts (is_active=false).
    """
    tenant_id = get_current_tenant_id()
    ruleset = rulesets_db.get_ruleset(ruleset_id, tenant_id, db_session)
    if not ruleset:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Ruleset not found")

    # Read the uploaded file content
    try:
        file_content = file.file.read()
    except Exception as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Failed to read uploaded file: {str(e)}",
        )

    if not file_content:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Uploaded file is empty")

    # Validate file size
    if len(file_content) > IMPORT_MAX_FILE_SIZE_BYTES:
        raise OnyxError(
            OnyxErrorCode.PAYLOAD_TOO_LARGE,
            f"File size {len(file_content)} bytes exceeds maximum "
            f"allowed size of {IMPORT_MAX_FILE_SIZE_BYTES} bytes",
        )

    # Extract text from the file
    # For text files, decode directly; for other formats, use extract_file_text
    extracted_text = ""
    filename = file.filename or "untitled"
    file_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if file_ext in ("txt", "text", "md"):
        extracted_text = file_content.decode("utf-8", errors="replace")
    else:
        try:
            import io

            from onyx.file_processing.extract_file_text import extract_file_text

            extracted_text = extract_file_text(
                file=io.BytesIO(file_content),
                file_name=filename,
            )
        except Exception as e:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Failed to extract text from file: {str(e)}",
            )

    if not extracted_text or not extracted_text.strip():
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "No text could be extracted from the uploaded file",
        )

    # Call the LLM-based checklist importer
    from onyx.server.features.proposal_review.engine.checklist_importer import (
        import_checklist,
    )

    try:
        rule_dicts = import_checklist(extracted_text)
    except RuntimeError as e:
        raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, str(e))

    # Save parsed rules to the ruleset as inactive drafts
    created_rules = []
    for rd in rule_dicts:
        rule = rulesets_db.create_rule(
            ruleset_id=ruleset_id,
            name=rd["name"],
            description=rd.get("description"),
            category=rd.get("category"),
            rule_type=rd.get("rule_type", "CUSTOM_NL"),
            rule_intent=rd.get("rule_intent", "CHECK"),
            prompt_template=rd["prompt_template"],
            source="IMPORTED",
            is_hard_stop=False,
            priority=0,
            db_session=db_session,
        )
        # Rules start as inactive drafts — admin reviews and activates
        rule.is_active = False
        db_session.flush()
        created_rules.append(rule)

    db_session.commit()
    return ImportResponse(
        rules_created=len(created_rules),
        rules=[RuleResponse.from_model(r) for r in created_rules],
    )


@router.post("/rules/{rule_id}/test")
def test_rule(
    rule_id: UUID,
    user: User = Depends(  # noqa: ARG001
        require_permission(Permission.MANAGE_CONNECTORS)
    ),
    db_session: Session = Depends(get_session),
) -> dict:
    """Test a rule against sample text.

    Evaluates the rule against an empty/minimal proposal context to verify
    the prompt template is well-formed and the LLM can produce a valid response.
    """
    # Verify the rule belongs to a ruleset owned by the current tenant
    tenant_id = get_current_tenant_id()
    rule = rulesets_db.get_rule(rule_id, db_session)
    if not rule:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Rule not found")
    ruleset = rulesets_db.get_ruleset(rule.ruleset_id, tenant_id, db_session)
    if not ruleset:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Rule not found")

    from onyx.server.features.proposal_review.engine.context_assembler import (
        ProposalContext,
    )
    from onyx.server.features.proposal_review.engine.rule_evaluator import (
        evaluate_rule,
    )

    # Build a minimal test context
    test_context = ProposalContext(
        proposal_text="[Sample proposal text for testing. No real proposal loaded.]",
        budget_text="[No budget text available for test.]",
        foa_text="[No FOA text available for test.]",
        metadata={"test_mode": True},
        jira_key="TEST-000",
    )

    try:
        result = evaluate_rule(rule, test_context, db_session)
    except Exception as e:
        return {
            "rule_id": str(rule_id),
            "success": False,
            "error": str(e),
        }

    return {
        "rule_id": str(rule_id),
        "success": True,
        "result": result,
    }
