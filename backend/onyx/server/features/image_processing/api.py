from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.image_processing import (
    delete_image_processing_settings,
    fetch_image_processing_settings,
    upsert_image_processing_settings,
)
from onyx.db.llm import fetch_model_configuration_by_id
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.utils import model_supports_image_input
from onyx.server.features.image_processing.models import (
    ImageProcessingSettingsResponse,
    ImageProcessingSettingsUpsertRequest,
)

admin_router = APIRouter(prefix="/admin/image-processing")


@admin_router.get("")
def get_image_processing_settings(
    _: User = Depends(require_permission(Permission.MANAGE_LLMS)),
    db_session: Session = Depends(get_session),
) -> ImageProcessingSettingsResponse | None:
    """The current image processing settings, or null when the feature is off."""
    row = fetch_image_processing_settings(db_session)
    return ImageProcessingSettingsResponse.from_model(row) if row else None


@admin_router.put("")
def put_image_processing_settings(
    request: ImageProcessingSettingsUpsertRequest,
    _: User = Depends(require_permission(Permission.MANAGE_LLMS)),
    db_session: Session = Depends(get_session),
) -> ImageProcessingSettingsResponse:
    """Turn image processing on with this model, or repoint it."""
    model_configuration = fetch_model_configuration_by_id(
        db_session, request.model_configuration_id
    )
    if model_configuration is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"model_configuration id={request.model_configuration_id} not found",
        )
    # The same rule the provider listing applies: the stored VISION flow,
    # else the LiteLLM cost map. Anything the picker offers is accepted here.
    provider = model_configuration.llm_provider
    if not model_supports_image_input(
        model_configuration.name, provider.provider, provider.deployment_name
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Model '{model_configuration.name}' does not support image input",
        )
    try:
        row = upsert_image_processing_settings(
            db_session=db_session,
            model_configuration_id=model_configuration.id,
            max_size_mb=request.max_size_mb,
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e))
    return ImageProcessingSettingsResponse.from_model(row)


@admin_router.delete("")
def delete_image_processing_settings_endpoint(
    _: User = Depends(require_permission(Permission.MANAGE_LLMS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Turn image processing off."""
    delete_image_processing_settings(db_session)
