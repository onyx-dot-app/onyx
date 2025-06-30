import json
from datetime import datetime
from typing import Any
from typing import Optional

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from pydantic import BaseModel
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
from onyx.federated_connectors.interfaces import FederatedConnectorBase
from onyx.server.models import StatusResponse
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/federated")


class FederatedConnectorCredentials(BaseModel):
    """Credentials for federated connector"""

    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    redirect_uri: Optional[str] = None
    # Add other common credential fields as needed

    class Config:
        extra = "allow"  # Allow additional fields for different connector types


class FederatedConnectorEntities(BaseModel):
    """Entities configuration for federated connector"""

    channels: Optional[list[str]] = None
    workspaces: Optional[list[str]] = None
    # Add other entity types as needed

    class Config:
        extra = "allow"  # Allow additional fields for different connector types


class FederatedConnectorRequest(BaseModel):
    source: FederatedConnectorSource
    credentials: FederatedConnectorCredentials


class FederatedConnectorResponse(BaseModel):
    id: int
    source: FederatedConnectorSource


class EntityValidationRequest(BaseModel):
    entities: FederatedConnectorEntities


class AuthorizeUrlResponse(BaseModel):
    authorize_url: str


class OAuthCallbackResult(BaseModel):
    access_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    refresh_token: Optional[str] = None
    token_type: Optional[str] = None
    scope: Optional[str] = None

    class Config:
        extra = "allow"  # Allow additional fields from different OAuth providers


class FederatedConnectorStatus(BaseModel):
    id: int
    source: FederatedConnectorSource
    name: str


class UserOAuthStatus(BaseModel):
    """OAuth status for a specific user and federated connector"""

    federated_connector_id: int
    source: FederatedConnectorSource
    name: str
    has_oauth_token: bool
    oauth_token_expires_at: Optional[datetime] = None
    authorize_url: Optional[str] = None


class FederatedConnectorDetail(BaseModel):
    id: int
    source: FederatedConnectorSource
    name: str
    credentials: FederatedConnectorCredentials
    oauth_token_exists: bool
    oauth_token_expires_at: Optional[datetime] = None
    document_sets: list[dict[str, Any]] = []


class FederatedConnectorUpdateRequest(BaseModel):
    credentials: Optional[FederatedConnectorCredentials] = None


class EntitySpecResponse(BaseModel):
    """Response for entity specification"""

    entities: dict[str, Any]


class CredentialSchemaResponse(BaseModel):
    """Response for credential schema specification"""

    credentials: dict[str, Any]


def _get_federated_connector_instance(
    source: FederatedConnectorSource,
    credentials: dict[str, Any] | None = None,
) -> FederatedConnectorBase:
    """Factory function to get the appropriate federated connector instance."""
    try:
        return get_federated_connector(source, credentials)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("")
def create_federated_connector(
    federated_connector_data: FederatedConnectorRequest,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> FederatedConnectorResponse:
    """Create a new federated connector"""
    tenant_id = get_current_tenant_id()

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
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> EntitySpecResponse:
    """Fetch allowed entities for the source type"""
    try:
        federated_connector = fetch_federated_connector_by_id(id, db_session)
        if not federated_connector:
            raise HTTPException(status_code=404, detail="Federated connector not found")

        connector_instance = _get_federated_connector_instance(
            federated_connector.source
        )
        entities_spec = connector_instance.entities()

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
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> CredentialSchemaResponse:
    """Fetch credential schema for the source type"""
    try:
        federated_connector = fetch_federated_connector_by_id(id, db_session)
        if not federated_connector:
            raise HTTPException(status_code=404, detail="Federated connector not found")

        connector_instance = _get_federated_connector_instance(
            federated_connector.source
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
    user: User = Depends(current_curator_or_admin_user),
) -> CredentialSchemaResponse:
    """Fetch credential schema for a specific source type (for setup forms)"""
    try:
        connector_instance = _get_federated_connector_instance(source)
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
        logger.error(f"Error fetching credentials schema for source {source}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sources/{source}/credentials/validate")
def validate_credentials(
    source: FederatedConnectorSource,
    credentials: FederatedConnectorCredentials,
    user: User = Depends(current_curator_or_admin_user),
) -> StatusResponse[bool]:
    """Validate credentials for a specific source type"""
    try:
        is_valid = validate_federated_connector_credentials(
            source, credentials.model_dump()
        )

        return StatusResponse(
            success=is_valid,
            message="Credentials are valid" if is_valid else "Credentials are invalid",
            data=is_valid,
        )

    except Exception as e:
        logger.error(f"Error validating credentials for source {source}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.head("/{id}/entities/validate")
def validate_entities(
    id: int,
    request: Request,
    user: User = Depends(current_curator_or_admin_user),
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

        # Convert to Pydantic model for validation
        entities = FederatedConnectorEntities(**entities_dict)

        connector_instance = _get_federated_connector_instance(
            federated_connector.source
        )
        is_valid = connector_instance.validate(entities.dict())

        if is_valid:
            return Response(status_code=200)
        else:
            return Response(status_code=400)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating entities for federated connector {id}: {e}")
        return Response(status_code=500)


@router.post("/{id}/entities/validate")
def validate_entities_post(
    id: int,
    validation_request: EntityValidationRequest,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[bool]:
    """Validate specified entities for source type (POST version for easier testing)"""
    try:
        federated_connector = fetch_federated_connector_by_id(id, db_session)
        if not federated_connector:
            raise HTTPException(status_code=404, detail="Federated connector not found")

        connector_instance = _get_federated_connector_instance(
            federated_connector.source
        )
        is_valid = connector_instance.validate(validation_request.entities.dict())

        return StatusResponse(
            success=is_valid,
            message="Entities are valid" if is_valid else "Entities are invalid",
            data=is_valid,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating entities for federated connector {id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{id}/authorize")
def get_authorize_url(
    id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> AuthorizeUrlResponse:
    """Get URL to send the user for OAuth"""
    try:
        federated_connector = fetch_federated_connector_by_id(id, db_session)
        if not federated_connector:
            raise HTTPException(status_code=404, detail="Federated connector not found")

        connector_instance = _get_federated_connector_instance(
            federated_connector.source, federated_connector.credentials
        )
        authorize_url = connector_instance.authorize()

        return AuthorizeUrlResponse(authorize_url=authorize_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting authorize URL for federated connector {id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{id}/callback")
def handle_oauth_callback(
    id: int,
    request: Request,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[OAuthCallbackResult]:
    """Handle callback and store OAuth result in DB"""
    try:
        federated_connector = fetch_federated_connector_by_id(id, db_session)
        if not federated_connector:
            raise HTTPException(status_code=404, detail="Federated connector not found")

        # Get callback data from request
        # For simplicity, we'll get data from query parameters
        # In a real implementation, you might want to handle both query params and form data
        callback_data = dict(request.query_params)

        connector_instance = _get_federated_connector_instance(
            federated_connector.source, federated_connector.credentials
        )
        oauth_result = connector_instance.callback(callback_data)

        # Convert OAuthResult to OAuthCallbackResult for API response
        oauth_result_dict = oauth_result.dict()
        oauth_callback_result = OAuthCallbackResult(**oauth_result_dict)

        # Store OAuth token in database
        if oauth_result.access_token and oauth_result.expires_at:
            update_federated_connector_oauth_token(
                db_session=db_session,
                federated_connector_id=id,
                user_id=user.id,
                token=oauth_result.access_token,
                expires_at=oauth_result.expires_at,
            )

        return StatusResponse(
            success=True,
            message="OAuth callback handled successfully",
            data=oauth_callback_result,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling OAuth callback for federated connector {id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
def get_federated_connectors(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[FederatedConnectorStatus]:
    """Get all federated connectors for display in the status table"""
    try:
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

    except Exception as e:
        logger.error(f"Error fetching federated connectors: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/oauth-status")
def get_user_oauth_status(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserOAuthStatus]:
    """Get OAuth status for all federated connectors for the current user"""
    try:
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
                try:
                    connector_instance = _get_federated_connector_instance(
                        fc.source, fc.credentials
                    )
                    authorize_url = connector_instance.authorize()
                except Exception as e:
                    logger.warning(
                        f"Failed to generate authorize URL for {fc.source}: {e}"
                    )

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

    except Exception as e:
        logger.error(f"Error getting user OAuth status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{id}")
def get_federated_connector_detail(
    id: int,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> FederatedConnectorDetail:
    """Get detailed information about a specific federated connector"""
    try:
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
            credentials=FederatedConnectorCredentials(
                **federated_connector.credentials
            ),
            oauth_token_exists=oauth_token is not None,
            oauth_token_expires_at=oauth_token.expires_at if oauth_token else None,
            document_sets=document_sets,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching federated connector {id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{id}")
def update_federated_connector_endpoint(
    id: int,
    update_request: FederatedConnectorUpdateRequest,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[FederatedConnectorDetail]:
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
        return StatusResponse(
            success=True,
            message="Federated connector updated successfully",
            data=get_federated_connector_detail(id, user, db_session),
        )

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Validation error updating federated connector {id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating federated connector {id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{id}")
def delete_federated_connector_endpoint(
    id: int,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[bool]:
    """Delete a federated connector"""
    try:
        success = delete_federated_connector(
            db_session=db_session,
            federated_connector_id=id,
        )

        if not success:
            raise HTTPException(status_code=404, detail="Federated connector not found")

        return StatusResponse(
            success=True,
            message="Federated connector deleted successfully",
            data=True,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting federated connector {id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{id}/oauth")
def disconnect_oauth_token(
    id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[bool]:
    """Disconnect OAuth token for the current user from a federated connector"""
    try:
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

            return StatusResponse(
                success=True,
                message="OAuth token disconnected successfully",
                data=True,
            )
        else:
            return StatusResponse(
                success=False,
                message="No OAuth token found for this user",
                data=False,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error disconnecting OAuth token for federated connector {id}: {e}"
        )
        raise HTTPException(status_code=500, detail=str(e))
