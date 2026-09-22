from pydantic import BaseModel, Field

from onyx.configs.app_configs import DEFAULT_IMAGE_ANALYSIS_MAX_SIZE_MB
from onyx.db.models import ImageProcessingSettings


class ImageProcessingSettingsResponse(BaseModel):
    model_configuration_id: int
    max_size_mb: int

    # This disables the "model_" protected namespace for pydantic
    model_config = {"protected_namespaces": ()}

    @classmethod
    def from_model(
        cls, row: ImageProcessingSettings
    ) -> "ImageProcessingSettingsResponse":
        return cls(
            model_configuration_id=row.model_configuration_id,
            max_size_mb=row.max_size_mb,
        )


class ImageProcessingSettingsUpsertRequest(BaseModel):
    model_configuration_id: int
    max_size_mb: int = Field(default=DEFAULT_IMAGE_ANALYSIS_MAX_SIZE_MB, gt=0)

    # This disables the "model_" protected namespace for pydantic
    model_config = {"protected_namespaces": ()}
