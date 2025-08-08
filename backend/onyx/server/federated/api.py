import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from sqlalchemy.orm import Session

from onyx.auth.users import current_curator_or_admin_user
from onyx.auth.users import current_user
from onyx.configs.constants import FederatedConnectorSource
from onyx.db.engine.sql_engine import get_session
from onyx.db.federated import (
    create_federated_connector as db_create_federated_connector,
)
from onyx.db.federated import delete_federated_connector
from onyx.db.federated import fetch_all_federated_connectors
from onyx.db.federated import fetch_federated_connector_by_id
from onyx.db.federated import update_federated_connector
from onyx.db.federated import update_federated_connector_oauth_token
from onyx.db.federated import validate_federated_connector_credentials
from onyx.db.models import User
from onyx.federated_connectors.factory import get_federated_connector
from onyx.federated_connectors.factory import get_federated_connector_cls
from onyx.federated_connectors.interfaces import FederatedConnector
from onyx.federated_connectors.oauth_utils import add_state_to_oauth_url
from onyx.federated_connectors.oauth_utils import generate_oauth_state
from onyx.federated_connectors.oauth_utils import get_oauth_callback_uri
from onyx.federated_connectors.oauth_utils import verify_oauth_state
from onyx.server.federated.models import AuthorizeUrlResponse
from onyx.server.federated.models import CredentialSchemaResponse
from onyx.server.federated.models import EntitySpecResponse
from onyx.server.federated.models import FederatedConnectorCredentials
from onyx.server.federated.models import FederatedConnectorDetail
from onyx.server.federated.models import FederatedConnectorRequest
from onyx.server.federated.models import FederatedConnectorResponse
from onyx.server.federated.models import FederatedConnectorStatus
from onyx.server.federated.models import FederatedConnectorUpdateRequest
from onyx.server.federated.models import OAuthCallbackResult
from onyx.server.federated.models import UserOAuthStatus
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/federated")


def _get_federated_connector_instance(
    source: FederatedConnectorSource,
    credentials: dict[str, Any],
) -> FederatedConnector:
    """Factory function to get the appropriate federated connector instance."""
    try:
        return get_federated_connector(source, credentials)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("")
def create_federated_connector(
    federated_connector_data: FederatedConnectorRequest,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> FederatedConnectorResponse:
    """Create a new federated connector"""
    tenant_id = get_current_tenant_id()

    if user is None:
        raise HTTPException(
            status_code=400,
            detail="Federated retrieval not supported with AUTH_TYPE=disabled.",
        )

    logger.info(
        f"Creating federated connector: source={federated_connector_data.source}, "
        f"user={user.email}, tenant_id={tenant_id}"
    )

    try:
        # Create the federated connector with validation
        federated_connector = db_create_federated_connector(
            db_session=db_session,
            source=federated_connector_data.source,
            credentials=federated_connector_data.credentials.model_dump(),
        )

        logger.info(
            f"Successfully created federated connector with id={federated_connector.id}"
        )

        return FederatedConnectorResponse(
            id=federated_connector.id,
            source=federated_connector.source,
        )

    except ValueError as e:
        logger.warning(f"Validation error creating federated connector: {e}")
        db_session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating federated connector: {e}")
        db_session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{id}/entities")
def get_entities(
    id: int,
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> EntitySpecResponse:
    """Fetch allowed entities for the source type"""
    try:
        federated_connector = fetch_federated_connector_by_id(id, db_session)
        if not federated_connector:
            raise HTTPException(status_code=404, detail="Federated connector not found")

        connector_instance = _get_federated_connector_instance(
            federated_connector.source, federated_connector.credentials
        )
        entities_spec = connector_instance.entities_schema()

        # Convert EntityField objects to a dictionary format for the API response
        entities_dict = {}
        for key, field in entities_spec.items():
            entities_dict[key] = {
                "type": field.type,
                "description": field.description,
                "required": field.required,
                "default": field.default,
                "example": field.example,
            }

        return EntitySpecResponse(entities=entities_dict)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching entities for federated connector {id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{id}/credentials/schema")
def get_credentials_schema(
    id: int,
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CredentialSchemaResponse:
    """Fetch credential schema for the source type"""
    try:
        federated_connector = fetch_federated_connector_by_id(id, db_session)
        if not federated_connector:
            raise HTTPException(status_code=404, detail="Federated connector not found")

        connector_instance = _get_federated_connector_instance(
            federated_connector.source, federated_connector.credentials
        )
        credentials_spec = connector_instance.credentials_schema()

        # Convert CredentialField objects to a dictionary format for the API response
        credentials_dict = {}
        for key, field in credentials_spec.items():
            credentials_dict[key] = {
                "type": field.type,
                "description": field.description,
                "required": field.required,
                "default": field.default,
                "example": field.example,
                "secret": field.secret,
            }

        return CredentialSchemaResponse(credentials=credentials_dict)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error fetching credentials schema for federated connector {id}: {e}"
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources/{source}/credentials/schema")
def get_credentials_schema_by_source(
    source: FederatedConnectorSource,
    _: User = Depends(current_curator_or_admin_user),
) -> CredentialSchemaResponse:
    """Fetch credential schema for a specific source type (for setup forms)"""
    try:
        connector_cls = get_federated_connector_cls(source)
        credentials_spec = connector_cls.credentials_schema()

        # Convert CredentialField objects to a dictionary format for the API response
        credentials_dict = {}
        for key, field in credentials_spec.items():
            credentials_dict[key] = {
                "type": field.type,
                "description": field.description,
                "required": field.required,
                "default": field.default,
                "example": field.example,
                "secret": field.secret,
            }

        return CredentialSchemaResponse(credentials=credentials_dict)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching credentials schema for source {source}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sources/{source}/credentials/validate")
def validate_credentials(
    source: FederatedConnectorSource,
    credentials: FederatedConnectorCredentials,
    _: User = Depends(current_curator_or_admin_user),
) -> bool:
    """Validate credentials for a specific source type"""
    try:
        is_valid = validate_federated_connector_credentials(
            source, credentials.model_dump()
        )

        if not is_valid:
            raise HTTPException(status_code=400, detail="Credentials are invalid")

        return is_valid

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating credentials for source {source}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.head("/{id}/entities/validate")
def validate_entities(
    id: int,
    request: Request,
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> Response:
    """Validate specified entities for source type"""
    try:
        federated_connector = fetch_federated_connector_by_id(id, db_session)
        if not federated_connector:
            raise HTTPException(status_code=404, detail="Federated connector not found")

        # For HEAD requests, we'll expect entities as query parameters
        # since HEAD requests shouldn't have request bodies
        entities_dict = {}
        query_params = dict(request.query_params)
        if "entities" in query_params:
            try:
                entities_dict = json.loads(query_params["entities"])
            except json.JSONDecodeError:
                logger.warning("Could not parse entities from query parameters")
                return Response(status_code=400)

        connector_instance = _get_federated_connector_instance(
            federated_connector.source, federated_connector.credentials
        )
        is_valid = connector_instance.validate_entities(entities_dict)

        if is_valid:
            return Response(status_code=200)
        else:
            return Response(status_code=400)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating entities for federated connector {id}: {e}")
        return Response(status_code=500)


@router.get("/{id}/authorize")
def get_authorize_url(
    id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> AuthorizeUrlResponse:
    """Get URL to send the user for OAuth"""
    # Validate that the ID is not None or invalid
    if id is None or id <= 0:
        raise HTTPException(status_code=400, detail="Invalid federated connector ID")

    federated_connector = fetch_federated_connector_by_id(id, db_session)
    if not federated_connector:
        raise HTTPException(status_code=404, detail="Federated connector not found")

    # Update credentials to include the correct redirect URI with the connector ID
    updated_credentials = federated_connector.credentials.copy()
    if "redirect_uri" in updated_credentials and updated_credentials["redirect_uri"]:
        # Replace the {id} placeholder with the actual federated connector ID
        updated_credentials["redirect_uri"] = updated_credentials[
            "redirect_uri"
        ].replace("{id}", str(id))

    connector_instance = _get_federated_connector_instance(
        federated_connector.source, updated_credentials
    )
    base_authorize_url = connector_instance.authorize(get_oauth_callback_uri())

    # Generate state parameter and store session info
    logger.info(
        f"Generating OAuth state for federated_connector_id={id}, user_id={user.id}"
    )
    state = generate_oauth_state(
        federated_connector_id=id,
        user_id=str(user.id),
    )

    # Add state to the OAuth URL
    authorize_url = add_state_to_oauth_url(base_authorize_url, state)
    logger.info(f"Generated OAuth authorize URL with state for connector {id}")
    return AuthorizeUrlResponse(authorize_url=authorize_url)


@router.post("/callback")
def handle_oauth_callback_generic(
    request: Request,
    _: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> OAuthCallbackResult:
    """Handle callback for any federated connector using state parameter"""
    # Get callback data from request (query parameters)
    callback_data = dict(request.query_params)

    # Verify state parameter and get session info
    state = callback_data.get("state")
    if not state:
        raise HTTPException(status_code=400, detail="Missing state parameter")

    try:
        oauth_session = verify_oauth_state(state)
    except ValueError:
        logger.exception("Error verifying OAuth state")
        raise HTTPException(
            status_code=400, detail="Invalid or expired state parameter"
        )

    if not oauth_session:
        raise HTTPException(
            status_code=400, detail="Invalid or expired state parameter"
        )

    # Get federated connector ID from the state
    federated_connector_id = oauth_session.federated_connector_id

    # Validate federated_connector_id is not None
    if federated_connector_id is None:
        logger.error("OAuth session has null federated_connector_id")
        raise HTTPException(
            status_code=400,
            detail="Invalid OAuth session: missing federated connector ID",
        )

    federated_connector = fetch_federated_connector_by_id(
        federated_connector_id, db_session
    )
    if not federated_connector:
        raise HTTPException(status_code=404, detail="Federated connector not found")

    connector_instance = _get_federated_connector_instance(
        federated_connector.source, federated_connector.credentials
    )
    oauth_result = connector_instance.callback(callback_data, get_oauth_callback_uri())

    # Convert OAuthResult to OAuthCallbackResult for API response
    oauth_result_dict = oauth_result.model_dump()
    oauth_callback_result = OAuthCallbackResult(**oauth_result_dict)

    # Add source information to the response
    oauth_callback_result.source = federated_connector.source

    # Store OAuth token in database if we have an access token
    if oauth_result.access_token:
        logger.info(
            f"Storing OAuth token for federated_connector_id={federated_connector_id}, "
            f"user_id={oauth_session.user_id}"
        )
        update_federated_connector_oauth_token(
            db_session=db_session,
            federated_connector_id=federated_connector_id,
            user_id=UUID(oauth_session.user_id),
            token=oauth_result.access_token,
            expires_at=oauth_result.expires_at,
        )

    return oauth_callback_result


@router.get("")
def get_federated_connectors(
    _: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[FederatedConnectorStatus]:
    """Get all federated connectors for display in the status table"""
    federated_connectors = fetch_all_federated_connectors(db_session)

    result = []
    for fc in federated_connectors:
        status_data = FederatedConnectorStatus(
            id=fc.id,
            source=fc.source,
            name=f"{fc.source.replace('_', ' ').title()}",
        )
        result.append(status_data)

    return result


@router.get("/oauth-status")
def get_user_oauth_status(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserOAuthStatus]:
    """Get OAuth status for all federated connectors for the current user"""
    federated_connectors = fetch_all_federated_connectors(db_session)

    result = []
    for fc in federated_connectors:
        # Check if user has OAuth token for this connector
        oauth_token = None
        for token in fc.oauth_tokens:
            if token.user_id == user.id:
                oauth_token = token
                break

        # Generate authorize URL if needed
        authorize_url = None
        if not oauth_token:
            connector_instance = _get_federated_connector_instance(
                fc.source, fc.credentials
            )
            base_authorize_url = connector_instance.authorize(get_oauth_callback_uri())

            # Generate state parameter and add to URL
            state = generate_oauth_state(
                federated_connector_id=fc.id,
                user_id=str(user.id),
            )
            authorize_url = add_state_to_oauth_url(base_authorize_url, state)

        status_data = UserOAuthStatus(
            federated_connector_id=fc.id,
            source=fc.source,
            name=f"{fc.source.replace('_', ' ').title()}",
            has_oauth_token=oauth_token is not None,
            oauth_token_expires_at=oauth_token.expires_at if oauth_token else None,
            authorize_url=authorize_url,
        )
        result.append(status_data)

    return result


@router.get("/{id}")
def get_federated_connector_detail(
    id: int,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> FederatedConnectorDetail:
    """Get detailed information about a specific federated connector"""
    federated_connector = fetch_federated_connector_by_id(id, db_session)
    if not federated_connector:
        raise HTTPException(status_code=404, detail="Federated connector not found")

    # Get OAuth token information for the current user
    oauth_token = None
    for token in federated_connector.oauth_tokens:
        if token.user_id == user.id:
            oauth_token = token
            break

    # Get document set mappings
    document_sets = []
    for mapping in federated_connector.document_sets:
        document_sets.append(
            {
                "id": mapping.document_set_id,
                "name": (
                    mapping.document_set.name if mapping.document_set else "Unknown"
                ),
                "entities": mapping.entities,
            }
        )

    return FederatedConnectorDetail(
        id=federated_connector.id,
        source=federated_connector.source,
        name=f"{federated_connector.source.replace('_', ' ').title()}",
        credentials=FederatedConnectorCredentials(**federated_connector.credentials),
        oauth_token_exists=oauth_token is not None,
        oauth_token_expires_at=oauth_token.expires_at if oauth_token else None,
        document_sets=document_sets,
    )


@router.put("/{id}")
def update_federated_connector_endpoint(
    id: int,
    update_request: FederatedConnectorUpdateRequest,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> FederatedConnectorDetail:
    """Update a federated connector's configuration"""
    try:
        # Update the federated connector
        updated_connector = update_federated_connector(
            db_session=db_session,
            federated_connector_id=id,
            credentials=(
                update_request.credentials.model_dump()
                if update_request.credentials
                else None
            ),
        )

        if not updated_connector:
            raise HTTPException(status_code=404, detail="Federated connector not found")

        # Return updated connector details
        return get_federated_connector_detail(id, user, db_session)

    except ValueError as e:
        logger.warning(f"Validation error updating federated connector {id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{id}")
def delete_federated_connector_endpoint(
    id: int,
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> bool:
    """Delete a federated connector"""
    success = delete_federated_connector(
        db_session=db_session,
        federated_connector_id=id,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Federated connector not found")

    return True


@router.delete("/{id}/oauth")
def disconnect_oauth_token(
    id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> bool:
    """Disconnect OAuth token for the current user from a federated connector"""
    # Check if the federated connector exists
    federated_connector = fetch_federated_connector_by_id(id, db_session)
    if not federated_connector:
        raise HTTPException(status_code=404, detail="Federated connector not found")

    # Find and delete the user's OAuth token
    oauth_token = None
    for token in federated_connector.oauth_tokens:
        if token.user_id == user.id:
            oauth_token = token
            break

    if oauth_token:
        db_session.delete(oauth_token)
        db_session.commit()
        return True
    else:
        raise HTTPException(
            status_code=404, detail="No OAuth token found for this user"
        )
