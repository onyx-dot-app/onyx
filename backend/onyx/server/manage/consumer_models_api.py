from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_API_KEY
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_ENABLED
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.user_preferences import update_user_default_model
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.consumer_model_catalog import ConsumerModelCatalogResponse
from onyx.llm.consumer_model_catalog import get_consumer_model_catalog_response
from onyx.llm.consumer_model_catalog import get_consumer_model_profile
from onyx.llm.consumer_model_catalog import profile_to_user_default_model
from onyx.llm.consumer_model_catalog import resolve_profile_id_from_user_default_model

router = APIRouter()


class ConsumerModelPreferenceRequest(BaseModel):
    profile_id: str


class ConsumerModelPreferenceResponse(BaseModel):
    profile_id: str


@router.get("/model-catalog")
def get_model_catalog(
    _: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> ConsumerModelCatalogResponse:
    if not CONSUMER_DEFAULT_LLM_ENABLED or not CONSUMER_DEFAULT_LLM_API_KEY:
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "模型服务暂不可用",
        )

    return get_consumer_model_catalog_response()


@router.get("/user/model-preference")
def get_user_model_preference(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> ConsumerModelPreferenceResponse:
    return ConsumerModelPreferenceResponse(
        profile_id=resolve_profile_id_from_user_default_model(user.default_model)
    )


@router.put("/user/model-preference")
def update_user_model_preference(
    request: ConsumerModelPreferenceRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ConsumerModelPreferenceResponse:
    profile = get_consumer_model_profile(request.profile_id)
    update_user_default_model(
        user.id,
        profile_to_user_default_model(profile),
        db_session,
    )
    return ConsumerModelPreferenceResponse(profile_id=profile.id)
