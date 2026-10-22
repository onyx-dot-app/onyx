import json
from collections import defaultdict

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.connectors.factory import parse_credential_binding, validate_ccpair_for_user
from onyx.db.connector_credential_pair import (
    get_manageable_cc_pairs_for_credentials,
    verify_user_can_edit_connector,
)
from onyx.db.credentials import (
    CREDENTIAL_PERMISSIONS_TO_IGNORE,
    CredentialAccessLevel,
    alter_credential,
    create_credential,
    delete_credential,
    delete_credential_for_user,
    fetch_credential_by_id_for_user,
    fetch_credential_group_ids,
    fetch_credentials_for_user,
    fetch_credentials_usable_by_source_for_user,
    fetch_editable_credential_ids,
    lock_credential__no_commit,
    swap_credentials_connector,
    update_credential,
    update_credential_sharing,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import Credential, DocumentSource, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.capability_check_runs import (
    start_capability_checks_for_new_credential,
)
from onyx.server.documents.draft_credentials import (
    validate_google_service_account_key,
)
from onyx.server.documents.models import (
    CredentialBase,
    CredentialDataUpdateRequest,
    CredentialSharing,
    CredentialSnapshot,
    CredentialSwapRequest,
    CredentialUsage,
    ObjectCreationIdResponse,
    SimilarCredentialSnapshot,
)
from onyx.server.documents.private_key_types import (
    FILE_TYPE_TO_FILE_PROCESSOR,
    PrivateKeyFileTypes,
    ProcessPrivateKeyFileProtocol,
)
from onyx.server.models import StatusResponse
from onyx.server.security.store import get_security_settings
from onyx.utils.audit import (
    AuditAction,
    AuditOutcome,
    actor_from_user,
    emit_audit_event,
)
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation

logger = setup_logger()


router = APIRouter(prefix="/manage", tags=PUBLIC_API_TAGS)


def _credential_snapshot(
    credential: Credential, user: User, db_session: Session
) -> CredentialSnapshot:
    return _credential_snapshots([credential], user, db_session)[0]


def credential_ids_to_mask(
    credentials: list[Credential], user: User, db_session: Session
) -> set[int]:
    """The credentials whose values the user must get masked: all of them when
    the workspace masks credentials, else those they cannot edit (a credential
    shared with their group, or the credential of a pair they only read or
    operate). Reuse of an account never reveals its secret."""
    credential_ids = {credential.id for credential in credentials}
    if get_security_settings().mask_credential_prefix:
        return credential_ids
    return credential_ids - fetch_editable_credential_ids(
        db_session, user, credential_ids
    )


def _credential_snapshots(
    credentials: list[Credential], user: User, db_session: Session
) -> list[CredentialSnapshot]:
    group_ids = fetch_credential_group_ids(
        db_session, [credential.id for credential in credentials]
    )
    masked_ids = credential_ids_to_mask(credentials, user, db_session)
    return [
        CredentialSnapshot.from_credential_db_model(
            credential,
            mask_credential_prefix=credential.id in masked_ids,
            viewer_id=user.id,
            group_ids=group_ids.get(credential.id),
        )
        for credential in credentials
    ]


"""Admin-only endpoints"""


@router.get("/admin/credential")
def list_credentials_admin(
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> list[CredentialSnapshot]:
    """Lists all public credentials"""
    credentials = fetch_credentials_for_user(
        db_session=db_session,
        user=user,
    )
    return _credential_snapshots(credentials, user, db_session)


@router.get("/admin/similar-credentials/{source_type}")
def get_cc_source_full_info(
    source_type: DocumentSource,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> list[SimilarCredentialSnapshot]:
    """The credentials a ``source_type`` connector can use, shown in that
    source's keys. Each lists the connectors using it that the user can manage,
    with their credential-bound config values, to help pick one."""
    credentials = fetch_credentials_usable_by_source_for_user(
        db_session=db_session,
        user=user,
        document_source=source_type,
    )
    if not credentials:
        return []
    usages: defaultdict[int, list[CredentialUsage]] = defaultdict(list)
    for cc_pair in get_manageable_cc_pairs_for_credentials(
        db_session, user, [credential.id for credential in credentials]
    ):
        connector = cc_pair.connector
        usages[cc_pair.credential_id].append(
            CredentialUsage(
                cc_pair_id=cc_pair.id,
                cc_pair_name=cc_pair.name,
                connector_id=connector.id,
                source=connector.source,
                credential_binding=parse_credential_binding(
                    connector.source, connector.connector_specific_config
                ),
            )
        )

    group_ids = fetch_credential_group_ids(
        db_session, [credential.id for credential in credentials]
    )
    masked_ids = credential_ids_to_mask(credentials, user, db_session)
    return [
        SimilarCredentialSnapshot(
            **dict(
                CredentialSnapshot.from_credential_db_model(
                    credential,
                    mask_credential_prefix=credential.id in masked_ids,
                    view_source=source_type,
                    viewer_id=user.id,
                    group_ids=group_ids.get(credential.id),
                )
            ),
            usages=usages[credential.id],
        )
        for credential in credentials
    ]


@router.delete("/admin/credential/{credential_id}")
def delete_credential_by_id_admin(
    credential_id: int,
    user: User = Depends(require_permission(Permission.MANAGE_CONNECTORS)),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    """Same as the user endpoint, but can delete any credential (not just the user's own)"""
    delete_credential(db_session=db_session, credential_id=credential_id)
    emit_audit_event(
        AuditAction.CREDENTIAL_DELETE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="credential",
        resource_id=credential_id,
    )
    return StatusResponse(
        success=True, message="Credential deleted successfully", data=credential_id
    )


@router.put("/admin/credential/swap")
def swap_credentials_for_connector(
    credential_swap_req: CredentialSwapRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    new_credential_id = credential_swap_req.new_credential_id

    # GATE 2 on the connector: swapping its credential is an Editor action.
    if not verify_user_can_edit_connector(
        credential_swap_req.connector_id, db_session, user
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Connection not found for current user's permissions",
        )

    # GATE 2 on the credential: validate_ccpair_for_user builds and probes the
    # connector, so ownership has to be settled before it runs.
    if fetch_credential_by_id_for_user(new_credential_id, user, db_session) is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {new_credential_id} does not exist or does not belong to user",
        )

    validate_ccpair_for_user(
        credential_swap_req.connector_id,
        new_credential_id,
        credential_swap_req.access_type,
        db_session,
        user=user,
    )

    connector_credential_pair = swap_credentials_connector(
        new_credential_id=new_credential_id,
        connector_id=credential_swap_req.connector_id,
        db_session=db_session,
        user=user,
    )

    return StatusResponse(
        success=True,
        message="Credential swapped successfully",
        data=connector_credential_pair.id,
    )


def assert_credential_share_within_scope(
    credential_info: CredentialBase, user: User, db_session: Session
) -> None:
    """GATE 2 for both create paths — they build the same CredentialBase, so the gate
    can't differ by transport."""
    assert_credential_sharing_allowed(
        user,
        db_session,
        source=credential_info.source,
        requested=CredentialSharing(
            admin_public=credential_info.admin_public,
            curator_public=credential_info.curator_public,
            groups=credential_info.groups,
        ),
    )


def assert_credential_sharing_allowed(
    user: User,
    db_session: Session,
    *,
    source: DocumentSource,
    requested: CredentialSharing,
    current_group_ids: list[int] | None = None,
    currently_curator_public: bool = False,
) -> None:
    """Checks the groups (EE only; they must exist), then GATE 2. Only sharing
    with groups or curators needs bounding: an unshared credential is private to
    its creator, and ``admin_public`` shares only with global admins. On an
    update, pass the current state read from the DB, never the client's.
    CREDENTIAL_PERMISSIONS_TO_IGNORE sources (file, web, wiki) carry no real
    secret and skip GATE 2."""
    validate_group_ids = fetch_versioned_implementation(
        "onyx.db.credentials", "validate_credential_group_ids"
    )
    validate_group_ids(db_session, requested.groups)

    current_group_ids = current_group_ids or []
    is_curator_public = requested.curator_public or currently_curator_public
    is_shared = bool(requested.groups or current_group_ids) or is_curator_public
    if is_shared and source not in CREDENTIAL_PERMISSIONS_TO_IGNORE:
        assert_within_scope(
            user,
            db_session,
            permission=Permission.MANAGE_CONNECTORS,
            current_group_ids=current_group_ids,
            requested_group_ids=requested.groups,
            is_non_public=not is_curator_public,
        )


@router.post("/credential")
def create_credential_from_model(
    credential_info: CredentialBase,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> ObjectCreationIdResponse:
    assert_credential_share_within_scope(credential_info, user, db_session)
    # A typed Google account can come here (the account dialog) as well as
    # through a draft, so its key is checked the same way.
    try:
        validate_google_service_account_key(
            credential_info.source, credential_info.credential_json
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e

    credential = create_credential(credential_info, user, db_session)
    emit_audit_event(
        AuditAction.CREDENTIAL_CREATE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="credential",
        resource_id=credential.id,
        extra={"source": credential_info.source.value},
    )
    start_capability_checks_for_new_credential(db_session, credential)
    return ObjectCreationIdResponse(
        id=credential.id,
        credential=_credential_snapshot(credential, user, db_session),
    )


@router.post("/credential/private-key")
def create_credential_with_private_key(
    credential_json: str = Form(...),
    admin_public: bool = Form(False),
    curator_public: bool = Form(False),
    groups: list[int] = Form([]),
    name: str | None = Form(None),
    source: str = Form(...),
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    uploaded_file: UploadFile = File(...),
    field_key: str = Form(...),
    type_definition_key: str = Form(...),
    db_session: Session = Depends(get_session),
) -> ObjectCreationIdResponse:
    try:
        credential_data = json.loads(credential_json)
    except json.JSONDecodeError as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, f"Invalid JSON in credential_json: {str(e)}"
        )

    private_key_processor: ProcessPrivateKeyFileProtocol | None = (
        FILE_TYPE_TO_FILE_PROCESSOR.get(PrivateKeyFileTypes(type_definition_key))
    )
    if private_key_processor is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Invalid type definition key for private key file",
        )
    private_key_content: str = private_key_processor(uploaded_file)

    credential_data[field_key] = private_key_content

    credential_info = CredentialBase(
        credential_json=credential_data,
        admin_public=admin_public,
        curator_public=curator_public,
        groups=groups,
        name=name,
        source=DocumentSource(source),
    )
    assert_credential_share_within_scope(credential_info, user, db_session)

    credential = create_credential(credential_info, user, db_session)
    emit_audit_event(
        AuditAction.CREDENTIAL_CREATE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="credential",
        resource_id=credential.id,
        extra={"source": credential_info.source.value},
    )
    start_capability_checks_for_new_credential(db_session, credential)
    return ObjectCreationIdResponse(
        id=credential.id,
        credential=_credential_snapshot(credential, user, db_session),
    )


"""Endpoints for all"""


@router.get("/credential")
def list_credentials(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[CredentialSnapshot]:
    credentials = fetch_credentials_for_user(db_session=db_session, user=user)
    return _credential_snapshots(credentials, user, db_session)


@router.get("/credential/{credential_id}")
def get_credential_by_id(
    credential_id: int,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> CredentialSnapshot | StatusResponse[int]:
    credential = fetch_credential_by_id_for_user(
        credential_id,
        user,
        db_session,
    )
    if credential is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {credential_id} does not exist or does not belong to user",
        )

    return _credential_snapshot(credential, user, db_session)


@router.put("/admin/credential/{credential_id}")
def update_credential_data(
    credential_id: int,
    credential_update: CredentialDataUpdateRequest,
    user: User = Depends(require_permission(Permission.MANAGE_CONNECTORS)),
    db_session: Session = Depends(get_session),
) -> CredentialBase:
    credential = alter_credential(
        credential_id,
        credential_update.name,
        credential_update.credential_json,
        user,
        db_session,
    )

    if credential is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {credential_id} does not exist or does not belong to user",
        )

    return _credential_snapshot(credential, user, db_session)


@router.put("/admin/credential/private-key/{credential_id}")
def update_credential_private_key(
    credential_id: int,
    name: str = Form(...),
    credential_json: str = Form(...),
    uploaded_file: UploadFile = File(...),
    field_key: str = Form(...),
    type_definition_key: str = Form(...),
    user: User = Depends(require_permission(Permission.MANAGE_CONNECTORS)),
    db_session: Session = Depends(get_session),
) -> CredentialBase:
    try:
        credential_data = json.loads(credential_json)
    except json.JSONDecodeError as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, f"Invalid JSON in credential_json: {str(e)}"
        )

    private_key_processor: ProcessPrivateKeyFileProtocol | None = (
        FILE_TYPE_TO_FILE_PROCESSOR.get(PrivateKeyFileTypes(type_definition_key))
    )
    if private_key_processor is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Invalid type definition key for private key file",
        )
    private_key_content: str = private_key_processor(uploaded_file)
    credential_data[field_key] = private_key_content

    credential = alter_credential(
        credential_id,
        name,
        credential_data,
        user,
        db_session,
    )

    if credential is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {credential_id} does not exist or does not belong to user",
        )

    return _credential_snapshot(credential, user, db_session)


@router.put("/admin/credential/{credential_id}/sharing")
def update_credential_sharing_endpoint(
    credential_id: int,
    sharing: CredentialSharing,
    user: User = Depends(
        require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
) -> CredentialSnapshot:
    """Changes who may reuse a saved credential. The owner, or an admin who can
    edit it, may do this. ``name`` changes the name when set."""
    # Held until update_credential_sharing commits: the current groups read
    # below must still be the groups the write replaces.
    lock_credential__no_commit(db_session, credential_id)
    credential = fetch_credential_by_id_for_user(
        credential_id, user, db_session, access_level=CredentialAccessLevel.EDIT
    )
    if credential is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {credential_id} does not exist or does not belong to user",
        )

    assert_credential_sharing_allowed(
        user,
        db_session,
        source=credential.source,
        requested=sharing,
        current_group_ids=fetch_credential_group_ids(db_session, [credential.id]).get(
            credential.id, []
        ),
        currently_curator_public=credential.curator_public,
    )

    update_credential_sharing(
        credential,
        admin_public=sharing.admin_public,
        curator_public=sharing.curator_public,
        groups=sharing.groups,
        name=sharing.name,
        db_session=db_session,
    )
    emit_audit_event(
        AuditAction.CREDENTIAL_UPDATE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="credential",
        resource_id=credential_id,
        extra={
            "admin_public": sharing.admin_public,
            "groups": sorted(set(sharing.groups)),
        },
    )
    return _credential_snapshot(credential, user, db_session)


@router.patch("/credential/{credential_id}")
def update_credential_from_model(
    credential_id: int,
    credential_data: CredentialBase,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> CredentialSnapshot | StatusResponse[int]:
    updated_credential = update_credential(
        credential_id, credential_data, user, db_session
    )
    if updated_credential is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {credential_id} does not exist or does not belong to user",
        )

    emit_audit_event(
        AuditAction.CREDENTIAL_UPDATE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="credential",
        resource_id=credential_id,
    )

    return _credential_snapshot(updated_credential, user, db_session)


@router.delete("/credential/{credential_id}")
def delete_credential_by_id(
    credential_id: int,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    delete_credential_for_user(
        credential_id,
        user,
        db_session,
    )

    emit_audit_event(
        AuditAction.CREDENTIAL_DELETE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="credential",
        resource_id=credential_id,
    )

    return StatusResponse(
        success=True, message="Credential deleted successfully", data=credential_id
    )


@router.delete("/credential/force/{credential_id}")
def force_delete_credential_by_id(
    credential_id: int,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    delete_credential_for_user(credential_id, user, db_session, True)

    emit_audit_event(
        AuditAction.CREDENTIAL_DELETE,
        AuditOutcome.SUCCESS,
        actor=actor_from_user(user),
        resource_type="credential",
        resource_id=credential_id,
    )

    return StatusResponse(
        success=True, message="Credential deleted successfully", data=credential_id
    )
