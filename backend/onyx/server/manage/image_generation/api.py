from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.image_generation import create_image_generation_config
from onyx.db.image_generation import delete_image_generation_config
from onyx.db.image_generation import get_all_image_generation_configs
from onyx.db.image_generation import set_default_image_generation_config
from onyx.db.models import User
from onyx.server.manage.image_generation.models import ImageGenerationConfigCreate
from onyx.server.manage.image_generation.models import ImageGenerationConfigView

admin_router = APIRouter(prefix="/admin/image-generation")


@admin_router.post("/config")
def create_config(
    config_create: ImageGenerationConfigCreate,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ImageGenerationConfigView:
    """Create a new image generation configuration."""
    try:
        config = create_image_generation_config(
            db_session=db_session,
            model_configuration_id=config_create.model_configuration_id,
            is_default=config_create.is_default,
        )
        # Refresh to load relationships
        db_session.refresh(config)
        return ImageGenerationConfigView.from_model(config)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@admin_router.get("/config")
def get_all_configs(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[ImageGenerationConfigView]:
    """Get all image generation configurations."""
    configs = get_all_image_generation_configs(db_session)
    return [ImageGenerationConfigView.from_model(config) for config in configs]


@admin_router.delete("/config/{config_id}")
def delete_config(
    config_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    """Delete an image generation configuration."""
    try:
        delete_image_generation_config(db_session, config_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@admin_router.post("/config/{config_id}/default")
def set_config_as_default(
    config_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    """Set a configuration as the default for image generation."""
    try:
        set_default_image_generation_config(db_session, config_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
