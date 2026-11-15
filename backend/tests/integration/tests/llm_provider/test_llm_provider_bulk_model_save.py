"""A large model list saves in one pass with every model and flow stored."""

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser

LARGE_MODEL_COUNT = 1500


def test_large_model_list_saves_every_model(new_admin_user: DATestUser) -> None:
    model_names = [f"bulk-model-{i:05d}" for i in range(LARGE_MODEL_COUNT)]
    provider = LLMProviderManager.create(
        user_performing_action=new_admin_user,
        default_model_name="bulk-default",
        model_names=model_names,
        set_as_default=False,
    )

    response = client.get(
        f"{API_SERVER_URL}/admin/llm/provider/{provider.id}",
        headers=new_admin_user.headers,
    )
    response.raise_for_status()
    models = response.json()["model_configurations"]
    assert {mc["name"] for mc in models} == {"bulk-default", *model_names}
    # The manager marks every model as accepting images, which is a flow row.
    assert all(mc["supports_image_input"] for mc in models)
