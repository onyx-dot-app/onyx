from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser


class ImageProcessingManager:
    """Drives `/admin/image-processing`, the on switch for image captioning."""

    @staticmethod
    def get(user_performing_action: DATestUser) -> dict | None:
        response = client.get(
            f"{API_SERVER_URL}/admin/image-processing",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def enable(
        user_performing_action: DATestUser,
        model_configuration_id: int,
        max_size_mb: int | None = None,
    ) -> dict:
        payload: dict[str, int] = {"model_configuration_id": model_configuration_id}
        if max_size_mb is not None:
            payload["max_size_mb"] = max_size_mb
        response = client.put(
            f"{API_SERVER_URL}/admin/image-processing",
            json=payload,
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def disable(user_performing_action: DATestUser) -> None:
        response = client.delete(
            f"{API_SERVER_URL}/admin/image-processing",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
