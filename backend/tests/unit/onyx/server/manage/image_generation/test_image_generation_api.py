from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from litellm.exceptions import BadRequestError

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.image_generation.api import (
    test_image_generation as run_test_image_generation,
)
from onyx.server.manage.image_generation.models import (
    TestImageGenerationRequest as ImageGenerationTestRequest,
)

_API_KEY = "sk-image-generation-secret"
_CUSTOM_SECRET = "custom-config-secret"


def test_image_generation_error_is_actionable_and_redacts_credentials() -> None:
    upstream_error = BadRequestError(
        message=(
            f"Unsupported image size. api_key={_API_KEY} custom_token={_CUSTOM_SECRET}"
        ),
        model="gpt-image-1",
        llm_provider="openai",
    )
    image_provider = MagicMock()
    image_provider.generate_image.side_effect = upstream_error
    request = ImageGenerationTestRequest(
        model_name="gpt-image-1",
        provider="openai",
        api_key=_API_KEY,
        custom_config={"custom_token": _CUSTOM_SECRET},
    )

    with (
        patch(
            "onyx.server.manage.image_generation.api.get_image_generation_provider",
            return_value=image_provider,
        ),
        pytest.raises(OnyxError) as exc_info,
    ):
        run_test_image_generation(request, MagicMock(), MagicMock())

    assert exc_info.value.error_code is OnyxErrorCode.VALIDATION_ERROR
    assert "Unsupported image size" in exc_info.value.detail
    assert exc_info.value.detail.count("[REDACTED]") == 2
    assert _API_KEY not in exc_info.value.detail
    assert _CUSTOM_SECRET not in exc_info.value.detail
