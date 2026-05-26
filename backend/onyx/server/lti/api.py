"""LTI 1.3 endpoints for Canvas (and other LMS) integration.

Implements the OIDC login initiation and launch callback required by the
LTI 1.3 spec, following the same session-issuance pattern as the SAML flow.

On launch, the LTI `context.id` from the JWT is what we use to discover
which Virtual Tutor personas a course is bound to. The binding is created
inside Onyx (see `TutorEditorPage` on the frontend) so admins never have
to type or paste a course ID — the launch handler threads `lti_context_id`
through to the editor and picker views via URL params.
"""

import secrets
import uuid
from urllib.parse import urlencode
from urllib.parse import urlparse

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Form
from fastapi import Path
from fastapi import Query
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse
from fastapi_users.authentication import Strategy
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.auth.users import auth_backend
from onyx.auth.users import current_chat_accessible_user
from onyx.auth.users import get_user_manager
from onyx.auth.users import UserManager
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.lti_configs import LTI_AUTH_LOGIN_URL
from onyx.configs.lti_configs import LTI_AUTH_TOKEN_URL
from onyx.configs.lti_configs import LTI_CANVAS_BASE_URL
from onyx.configs.lti_configs import LTI_CLIENT_ID
from onyx.configs.lti_configs import LTI_DEPLOYMENT_ID
from onyx.configs.lti_configs import LTI_ISSUER
from onyx.configs.lti_configs import LTI_JWKS_URL
from onyx.connectors.canvas.client import CanvasApiClient
from onyx.connectors.canvas.connector import CanvasCourse
from onyx.connectors.models import InputType
from onyx.db.connector import connector_by_name_source_exists
from onyx.db.connector import create_connector
from onyx.db.connector import fetch_canvas_cc_pair_for_lti_course
from onyx.db.connector import mark_ccpair_with_indexing_trigger
from onyx.db.connector_credential_pair import add_credential_to_connector
from onyx.db.credentials import create_credential
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import AccessType
from onyx.db.enums import IndexingMode
from onyx.db.index_attempt import get_latest_index_attempt_for_cc_pair_id
from onyx.db.models import User
from onyx.db.persona import get_tutor_persona_snapshots_for_course
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.redis.redis_pool import get_raw_redis_client
from onyx.server.documents.models import ConnectorBase
from onyx.server.documents.models import CredentialBase
from onyx.server.features.persona.models import MinimalPersonaSnapshot
from onyx.server.lti.jwks import get_public_jwks
from onyx.server.lti.utils import _extract_email_from_claims
from onyx.server.lti.utils import extract_lti_context
from onyx.server.lti.utils import find_canvas_course_node_id
from onyx.server.lti.utils import find_tutor_personas_for_course
from onyx.server.lti.utils import get_lti_launch_context
from onyx.server.lti.utils import get_or_create_lti_course_project
from onyx.server.lti.utils import lti_roles_include_instructor
from onyx.server.lti.utils import LtiLaunchContext
from onyx.server.lti.utils import store_lti_launch_context
from onyx.server.lti.utils import store_lti_state
from onyx.server.lti.utils import upsert_lti_user
from onyx.server.lti.utils import validate_and_consume_state
from onyx.server.lti.utils import validate_lti_jwt
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id


logger = setup_logger()
router = APIRouter(prefix="/auth/lti")
_CHECK_FOR_INDEXING_EXPIRES_SECONDS = 15 * 60
_LTI_LAUNCH_PRESENTATION_CLAIM = (
    "https://purl.imsglobal.org/spec/lti/claim/launch_presentation"
)
_CANVAS_GLOBAL_LTI_HOSTS = {
    "canvas.instructure.com",
    "canvas.beta.instructure.com",
    "canvas.test.instructure.com",
    "sso.canvaslms.com",
    "sso.beta.canvaslms.com",
    "sso.test.canvaslms.com",
}


class LtiCanvasConnectorSetupRequest(BaseModel):
    canvas_access_token: str = Field(min_length=1)


class LtiCanvasConnectorSetupResponse(BaseModel):
    cc_pair_id: int
    connector_id: int
    credential_id: int
    created: bool


def _origin_from_url(raw_url: str | None) -> str | None:
    if not raw_url:
        return None

    parsed_url = urlparse(raw_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        return None

    return f"{parsed_url.scheme}://{parsed_url.netloc}"


def _is_canvas_global_lti_host(raw_url: str) -> bool:
    parsed_url = urlparse(raw_url)
    hostname = parsed_url.hostname
    return hostname in _CANVAS_GLOBAL_LTI_HOSTS


def _canvas_base_url_from_request_headers(request: Request) -> str | None:
    return _origin_from_url(request.headers.get("origin")) or _origin_from_url(
        request.headers.get("referer")
    )


def _launch_presentation_claim(claims: dict) -> dict[str, object]:
    launch_presentation = claims.get(_LTI_LAUNCH_PRESENTATION_CLAIM)
    return launch_presentation if isinstance(launch_presentation, dict) else {}


def _canvas_base_url_from_lti_claims(claims: dict) -> str | None:
    return_url = _launch_presentation_claim(claims).get("return_url")
    return _origin_from_url(str(return_url)) if return_url else None


def _canvas_course_id_from_url(raw_url: str | None) -> int | None:
    if not raw_url:
        return None

    parsed_url = urlparse(raw_url)
    path_parts = [part for part in parsed_url.path.split("/") if part]
    for index, path_part in enumerate(path_parts[:-1]):
        if path_part != "courses":
            continue
        course_id = path_parts[index + 1]
        if course_id.isdigit():
            return int(course_id)
    return None


def _canvas_course_id_from_lti_claims(claims: dict) -> int | None:
    return_url = _launch_presentation_claim(claims).get("return_url")
    return _canvas_course_id_from_url(str(return_url)) if return_url else None


def _get_launch_context_for_course_or_raise(
    user: User,
    course_id: str,
) -> LtiLaunchContext:
    redis_client = get_raw_redis_client()
    launch_context = get_lti_launch_context(redis_client, user.id)
    if launch_context is None:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "No active LTI launch context found for this session",
        )
    if launch_context.course_id != course_id:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "LTI course context does not match this request",
        )
    return launch_context


def _canvas_base_url_from_issuer(issuer: str | None) -> str:
    if not issuer:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "LTI issuer is not available for this launch",
        )

    parsed_issuer = urlparse(issuer)
    if not parsed_issuer.scheme or not parsed_issuer.netloc:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "LTI issuer is not a valid URL",
        )
    return f"{parsed_issuer.scheme}://{parsed_issuer.netloc}"


def _canvas_token_settings_url(canvas_base_url: str) -> str:
    return f"{canvas_base_url}/profile/settings"


def _canvas_base_url_from_lti_config() -> str | None:
    if LTI_CANVAS_BASE_URL:
        return _origin_from_url(LTI_CANVAS_BASE_URL)

    for configured_url in (LTI_AUTH_TOKEN_URL, LTI_JWKS_URL, LTI_AUTH_LOGIN_URL):
        if not configured_url or _is_canvas_global_lti_host(configured_url):
            continue
        origin = _origin_from_url(configured_url)
        if origin:
            return origin

    return None


def _canvas_base_url_for_launch_context(launch_context: LtiLaunchContext) -> str:
    if launch_context.canvas_base_url:
        return launch_context.canvas_base_url
    configured_canvas_base_url = _canvas_base_url_from_lti_config()
    if configured_canvas_base_url:
        return configured_canvas_base_url
    return _canvas_base_url_from_issuer(launch_context.issuer or LTI_ISSUER)


def _course_text_matches(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    return left.strip().casefold() == right.strip().casefold()


def _resolve_canvas_api_course(
    canvas_client: CanvasApiClient,
    launch_context: LtiLaunchContext,
) -> CanvasCourse:
    if launch_context.canvas_course_id is not None:
        try:
            course_payload, _ = canvas_client.get(
                f"courses/{launch_context.canvas_course_id}"
            )
            if isinstance(course_payload, dict):
                return CanvasCourse.from_api(course_payload)
        except OnyxError as e:
            if e.status_code in (401, 403, 404):
                raise OnyxError(
                    OnyxErrorCode.CREDENTIAL_INVALID,
                    "Canvas token could not access the launched course",
                ) from e
            raise

    lti_course_id = launch_context.course_id.strip()
    if lti_course_id.isdigit():
        try:
            course_payload, _ = canvas_client.get(f"courses/{lti_course_id}")
            if isinstance(course_payload, dict):
                return CanvasCourse.from_api(course_payload)
        except OnyxError as e:
            if e.status_code not in (403, 404):
                raise

    matching_courses: list[CanvasCourse] = []
    for page in canvas_client.paginate(
        "courses", params={"per_page": "100", "state[]": "available"}
    ):
        for raw_course in page:
            if not isinstance(raw_course, dict):
                continue
            course = CanvasCourse.from_api(raw_course)
            title_matches = _course_text_matches(
                course.name, launch_context.course_title
            )
            label_matches = _course_text_matches(
                course.course_code, launch_context.course_label
            )
            if title_matches or label_matches:
                matching_courses.append(course)

    if len(matching_courses) == 1:
        return matching_courses[0]

    if len(matching_courses) > 1:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Canvas token matched multiple courses for this LTI launch",
        )

    raise OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        "Canvas token could not access the launched course",
    )


def _validate_canvas_token_and_resolve_course(
    canvas_access_token: str,
    canvas_base_url: str,
    launch_context: LtiLaunchContext,
) -> CanvasCourse:
    try:
        logger.info(
            "Validating Canvas LTI connector token against %s for course context %s",
            canvas_base_url,
            launch_context.course_id,
        )
        canvas_client = CanvasApiClient(
            bearer_token=canvas_access_token,
            canvas_base_url=canvas_base_url,
        )
        canvas_client.get("users/self")
        return _resolve_canvas_api_course(canvas_client, launch_context)
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e
    except OnyxError as e:
        if e.status_code in (401, 403):
            raise OnyxError(
                OnyxErrorCode.CREDENTIAL_INVALID,
                "Canvas token could not be validated for this course",
            ) from e
        raise


def _build_canvas_connector_name(
    launch_context: LtiLaunchContext,
    db_session: Session,
) -> str:
    name_parts = ["Canvas"]
    if launch_context.course_label:
        name_parts.append(launch_context.course_label.strip())
    if launch_context.course_title:
        name_parts.append(launch_context.course_title.strip())
    if len(name_parts) == 1:
        name_parts.append(f"Course {launch_context.course_id}")

    base_name = " - ".join(part for part in name_parts if part)
    if not connector_by_name_source_exists(
        base_name, DocumentSource.CANVAS, db_session
    ):
        return base_name

    name_with_context = f"{base_name} ({launch_context.course_id})"
    if not connector_by_name_source_exists(
        name_with_context, DocumentSource.CANVAS, db_session
    ):
        return name_with_context

    return f"{name_with_context} {uuid.uuid4().hex[:8]}"


def _build_lti_course_connector_status(
    *,
    course_id: str,
    launch_context: LtiLaunchContext,
    db_session: Session,
) -> dict[str, object]:
    cc_pair = fetch_canvas_cc_pair_for_lti_course(
        db_session=db_session,
        lti_context_id=course_id,
    )
    status: dict[str, object] = {
        "course_id": course_id,
        "has_connector": cc_pair is not None,
        "cc_pair_id": None,
        "connector_id": None,
        "credential_id": None,
        "cc_pair_status": None,
        "indexing_status": None,
        "indexing_trigger": None,
        "total_docs_indexed": 0,
        "has_indexed_documents": False,
        "last_successful_index_time": None,
    }

    if cc_pair is not None:
        latest_attempt = get_latest_index_attempt_for_cc_pair_id(
            db_session=db_session,
            connector_credential_pair_id=cc_pair.id,
            secondary_index=False,
            only_finished=False,
        )
        total_docs_indexed = cc_pair.total_docs_indexed or 0
        status.update(
            {
                "cc_pair_id": cc_pair.id,
                "connector_id": cc_pair.connector_id,
                "credential_id": cc_pair.credential_id,
                "cc_pair_status": cc_pair.status,
                "indexing_status": latest_attempt.status if latest_attempt else None,
                "indexing_trigger": cc_pair.indexing_trigger,
                "total_docs_indexed": total_docs_indexed,
                "has_indexed_documents": total_docs_indexed > 0,
                "last_successful_index_time": cc_pair.last_successful_index_time,
            }
        )

    if lti_roles_include_instructor(launch_context.roles):
        canvas_base_url = _canvas_base_url_for_launch_context(launch_context)
        status["setup"] = {
            "can_setup": cc_pair is None,
            "canvas_token_url": _canvas_token_settings_url(canvas_base_url),
            "course_label": launch_context.course_label,
            "course_title": launch_context.course_title,
        }

    return status


@router.get("/tutors-for-course")
def lti_tutors_for_course(
    context_id: str = Query(..., min_length=1),
    user: User = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> list[MinimalPersonaSnapshot]:
    """Return Virtual Tutor personas bound to a given LTI course context.

    Used by the in-app picker (`TutorPickerView`) and the instructor manage
    view to list every tutor available for the current course. Access is
    filtered by the standard persona access rules — students only see
    tutors they can already reach.
    """
    return get_tutor_persona_snapshots_for_course(
        user=user,
        lti_context_id=context_id,
        db_session=db_session,
    )


@router.get("/course/{course_id}/connector-status")
def lti_course_connector_status(
    course_id: str = Path(..., min_length=1),
    user: User = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> dict[str, object]:
    launch_context = _get_launch_context_for_course_or_raise(user, course_id)
    return _build_lti_course_connector_status(
        course_id=course_id,
        launch_context=launch_context,
        db_session=db_session,
    )


@router.post("/course/{course_id}/setup-connector")
def setup_lti_course_canvas_connector(
    setup_request: LtiCanvasConnectorSetupRequest,
    course_id: str = Path(..., min_length=1),
    user: User = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> LtiCanvasConnectorSetupResponse:
    launch_context = _get_launch_context_for_course_or_raise(user, course_id)
    if not lti_roles_include_instructor(launch_context.roles):
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "Only instructors can set up Canvas course content",
        )

    existing_cc_pair = fetch_canvas_cc_pair_for_lti_course(
        db_session=db_session,
        lti_context_id=course_id,
    )
    if existing_cc_pair is not None:
        return LtiCanvasConnectorSetupResponse(
            cc_pair_id=existing_cc_pair.id,
            connector_id=existing_cc_pair.connector_id,
            credential_id=existing_cc_pair.credential_id,
            created=False,
        )

    canvas_base_url = _canvas_base_url_for_launch_context(launch_context)
    canvas_course = _validate_canvas_token_and_resolve_course(
        canvas_access_token=setup_request.canvas_access_token,
        canvas_base_url=canvas_base_url,
        launch_context=launch_context,
    )
    connector_name = _build_canvas_connector_name(
        launch_context=launch_context,
        db_session=db_session,
    )

    try:
        connector_response = create_connector(
            db_session=db_session,
            connector_data=ConnectorBase(
                name=connector_name,
                source=DocumentSource.CANVAS,
                input_type=InputType.POLL,
                connector_specific_config={
                    "canvas_base_url": canvas_base_url,
                    "course_ids": [canvas_course.id],
                    "lti_context_id": launch_context.course_id,
                },
            ),
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.DUPLICATE_RESOURCE, str(e)) from e

    connector_id = int(connector_response.id)
    credential = create_credential(
        credential_data=CredentialBase(
            credential_json={
                "canvas_access_token": setup_request.canvas_access_token,
            },
            admin_public=False,
            source=DocumentSource.CANVAS,
            name=f"{connector_name} credential",
        ),
        user=user,
        db_session=db_session,
    )

    cc_pair_response = add_credential_to_connector(
        db_session=db_session,
        user=user,
        connector_id=connector_id,
        credential_id=credential.id,
        cc_pair_name=connector_name,
        access_type=AccessType.SYNC,
        groups=[],
    )
    if not cc_pair_response.success or cc_pair_response.data is None:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            cc_pair_response.message,
        )

    cc_pair_id = int(cc_pair_response.data)
    mark_ccpair_with_indexing_trigger(
        cc_pair_id=cc_pair_id,
        indexing_mode=IndexingMode.REINDEX,
        db_session=db_session,
    )
    client_app.send_task(
        OnyxCeleryTask.CHECK_FOR_INDEXING,
        priority=OnyxCeleryPriority.HIGH,
        kwargs={"tenant_id": get_current_tenant_id()},
        expires=_CHECK_FOR_INDEXING_EXPIRES_SECONDS,
    )

    return LtiCanvasConnectorSetupResponse(
        cc_pair_id=cc_pair_id,
        connector_id=connector_id,
        credential_id=credential.id,
        created=True,
    )


@router.get("/jwks")
async def lti_jwks() -> JSONResponse:
    """Serve Onyx's public JWKS for LTI 1.3.

    Canvas requires a Public JWK URL during Developer Key setup.
    This key would be used for signing service requests back to
    Canvas (LTI Advantage), but is also required for basic setup.
    """
    return JSONResponse(content=get_public_jwks())


@router.api_route("/login", methods=["GET", "POST"])
async def lti_login(
    request: Request,
) -> RedirectResponse:
    """OIDC Login Initiation (Step 1 of LTI 1.3 launch).

    Canvas sends this as a POST (form-encoded) or GET (query params).
    We accept both and read parameters from whichever source is available.
    """
    # Read params from form body (POST) or query string (GET)
    if request.method == "POST":
        form_data = await request.form()
        params_dict = dict(form_data)
    else:
        params_dict = dict(request.query_params)

    logger.info(
        "LTI login initiation: method=%s, params=%s, query=%s, headers=%s",
        request.method,
        params_dict,
        dict(request.query_params),
        {
            k: v
            for k, v in request.headers.items()
            if k.lower() in ("content-type", "host", "referer", "origin")
        },
    )

    iss = str(params_dict.get("iss", ""))
    login_hint = str(params_dict.get("login_hint", ""))
    str(params_dict.get("target_link_uri", ""))
    lti_message_hint = params_dict.get("lti_message_hint")
    if lti_message_hint is not None:
        lti_message_hint = str(lti_message_hint)
    client_id = params_dict.get("client_id")
    if client_id is not None:
        client_id = str(client_id)

    if not iss or not login_hint:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Missing required LTI login parameters (iss, login_hint)",
        )

    # Validate the issuer matches our configured platform
    if iss != LTI_ISSUER:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Unknown LTI issuer: {iss}",
        )

    if client_id and client_id != LTI_CLIENT_ID:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Unknown LTI client_id: {client_id}",
        )

    if not LTI_AUTH_LOGIN_URL or not LTI_CLIENT_ID:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "LTI is not fully configured on this Onyx instance",
        )

    # Generate nonce and state for OIDC flow
    nonce = secrets.token_urlsafe(32)
    state = secrets.token_urlsafe(32)

    # Store in Redis for validation on callback
    redis = await get_async_redis_connection()
    await store_lti_state(
        redis,
        state,
        nonce,
        canvas_base_url=_canvas_base_url_from_request_headers(request),
    )

    # Build the redirect URL back to the LMS authorization endpoint
    redirect_uri = f"{WEB_DOMAIN}/auth/lti/launch"
    params = {
        "scope": "openid",
        "response_type": "id_token",
        "client_id": LTI_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "login_hint": login_hint,
        "state": state,
        "response_mode": "form_post",
        "nonce": nonce,
        "prompt": "none",
    }
    if lti_message_hint is not None:
        params["lti_message_hint"] = lti_message_hint

    auth_url = f"{LTI_AUTH_LOGIN_URL}?{urlencode(params)}"
    return RedirectResponse(url=auth_url, status_code=302)


@router.post("/launch")
async def lti_launch(
    request: Request,
    id_token: str = Form(...),
    state: str = Form(...),
    user_manager: UserManager = Depends(get_user_manager),
    strategy: Strategy[User, uuid.UUID] = Depends(auth_backend.get_strategy),
) -> RedirectResponse:
    """LTI 1.3 Launch Callback (Step 2).

    Canvas auto-submits a form POST with the signed JWT (id_token) and
    state. We validate everything, provision the user, issue a session,
    and redirect into the embedded chat UI.
    """
    # Validate and consume the state (atomic -- prevents replay)
    redis = await get_async_redis_connection()
    lti_state = await validate_and_consume_state(redis, state)

    # Validate the JWT
    claims = await validate_lti_jwt(id_token, lti_state.nonce)

    # Verify deployment ID if present
    deployment_id = claims.get(
        "https://purl.imsglobal.org/spec/lti/claim/deployment_id"
    )
    if deployment_id and LTI_DEPLOYMENT_ID and deployment_id != LTI_DEPLOYMENT_ID:
        raise OnyxError(
            OnyxErrorCode.UNAUTHENTICATED,
            f"LTI deployment ID mismatch: {deployment_id}",
        )

    # Extract user info
    email = _extract_email_from_claims(claims)
    raw_lti_roles = claims.get("https://purl.imsglobal.org/spec/lti/claim/roles", [])
    lti_roles = (
        [str(role) for role in raw_lti_roles] if isinstance(raw_lti_roles, list) else []
    )

    logger.info("LTI launch for user %s with roles %s", email, lti_roles)

    # JIT provision or retrieve the user
    user = await upsert_lti_user(email, lti_roles)

    # Issue a session (same pattern as SAML)
    response = await auth_backend.login(strategy, user)
    await user_manager.on_after_login(user, request, response)

    # Override cookie attributes for iframe embedding
    _patch_cookie_for_embedding(response)

    # Extract course context and create/find a project for it
    context = extract_lti_context(claims)
    custom_claims = claims.get("https://purl.imsglobal.org/spec/lti/claim/custom", {})
    assistant_id = custom_claims.get("assistant_id")
    canvas_base_url = (
        _canvas_base_url_from_lti_claims(claims)
        or _canvas_base_url_from_request_headers(request)
        or lti_state.canvas_base_url
    )
    canvas_course_id = _canvas_course_id_from_lti_claims(claims)

    # Build redirect URL — send students to /tutor, not /app
    redirect_params: dict[str, str] = {}

    # The LTI `context.id` is the canonical, stable identifier we bind tutors
    # against. We always pass it through so the picker view and editor can
    # find / create / list tutors for this course without any admin typing.
    course_id = context.get("course_id")
    course_title = context.get("course_title")
    if course_id:
        redirect_params["lti_context_id"] = course_id
        await store_lti_launch_context(
            redis=redis,
            user_id=user.id,
            launch_context=LtiLaunchContext(
                course_id=course_id,
                course_label=context.get("course_label"),
                course_title=course_title,
                roles=lti_roles,
                issuer=str(claims.get("iss") or LTI_ISSUER or ""),
                canvas_base_url=canvas_base_url,
                canvas_course_id=canvas_course_id,
            ),
        )

    # Try to resolve the Canvas course's indexed hierarchy node so the editor
    # can scope its knowledge picker to just this course's contents. Optional:
    # if the connector hasn't indexed the course (or two courses share a
    # title) we leave it out and fall back to the full hierarchy.
    if course_title:
        canvas_node_id = await find_canvas_course_node_id(course_title)
        if canvas_node_id is not None:
            redirect_params["lti_canvas_course_node_id"] = str(canvas_node_id)

    # Resolve which tutor persona to use:
    # 1. Explicit assistant_id from a Canvas custom claim (rare; admin override).
    # 2. Auto-discover Virtual Tutor personas bound to this `context.id`.
    #    - 0 matches → no `agentId` set; picker view handles it.
    #    - 1 match → set `agentId` and drop the user straight into the chat.
    #    - 2+ matches → no `agentId` set; picker view lets the student choose.
    if assistant_id:
        redirect_params["assistantId"] = str(assistant_id)
    elif course_id:
        discovered_ids = await find_tutor_personas_for_course(course_id)
        if len(discovered_ids) == 1:
            redirect_params["assistantId"] = str(discovered_ids[0])

    # Create/find a UserProject for the Canvas course so conversations
    # are scoped per-course
    if course_id:
        project_id = await get_or_create_lti_course_project(
            user_id=user.id,
            course_id=course_id,
            course_label=context.get("course_label"),
            course_title=context.get("course_title"),
        )
        redirect_params["projectId"] = str(project_id)

    query_string = urlencode(redirect_params) if redirect_params else ""
    redirect_url = f"{WEB_DOMAIN}/tutor"
    if query_string:
        redirect_url += f"?{query_string}"

    # Transfer cookies from the login response to the redirect
    redirect_response = RedirectResponse(url=redirect_url, status_code=302)
    for header_name, header_value in response.headers.items():
        if header_name.lower() == "set-cookie":
            redirect_response.headers.append("set-cookie", header_value)

    return redirect_response


def _patch_cookie_for_embedding(response: object) -> None:
    """Rewrite Set-Cookie headers so the session cookie works inside an iframe.

    The CookieTransport from fastapi-users sets SameSite=Lax by default,
    which blocks the cookie in a cross-origin iframe. We need
    SameSite=None; Secure; Partitioned for CHIPS support.
    """
    from starlette.responses import Response as StarletteResponse

    if not isinstance(response, StarletteResponse):
        return

    patched_raw: list[tuple[bytes, bytes]] = []
    for key, value in response.headers.raw:
        if key.lower() == b"set-cookie":
            cookie_str = value.decode("latin-1")
            # Replace SameSite=Lax with SameSite=None
            cookie_str = cookie_str.replace("SameSite=lax", "SameSite=None")
            cookie_str = cookie_str.replace("SameSite=Lax", "SameSite=None")
            # Ensure Secure flag is present (required for SameSite=None)
            if "Secure" not in cookie_str:
                cookie_str += "; Secure"
            # Add Partitioned for CHIPS support
            if "Partitioned" not in cookie_str:
                cookie_str += "; Partitioned"
            patched_raw.append((key, cookie_str.encode("latin-1")))
        else:
            patched_raw.append((key, value))

    # Replace the raw header list in-place
    response.headers.raw.clear()
    response.headers.raw.extend(patched_raw)
