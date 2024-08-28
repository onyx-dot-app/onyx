import os
from typing import cast

import requests
from pydantic import BaseModel
from pydantic import PrivateAttr

from danswer.server.manage.llm.models import LLMProviderUpsertRequest
from tests.integration.common_utils.constants import API_SERVER_URL


class LLMProvider(BaseModel):
    provider: str
    api_key: str
    default_model_name: str
    api_base: str | None = None
    api_version: str | None = None
    is_default: bool = True

    # only populated after creation
    _provider_id: int | None = PrivateAttr()

    def create(self) -> int:
        llm_provider = LLMProviderUpsertRequest(
            name=self.provider,
            provider=self.provider,
            default_model_name=self.default_model_name,
            api_key=self.api_key,
            api_base=self.api_base,
            api_version=self.api_version,
            custom_config=None,
            fast_default_model_name=None,
            is_public=True,
            groups=None,
            display_model_names=None,
            model_names=None,
        )

        response = requests.put(
            f"{API_SERVER_URL}/admin/llm/provider",
            json=llm_provider.dict(),
        )
        response.raise_for_status()

        self._provider_id = cast(int, response.json()["id"])
        return self._provider_id

    def delete(self) -> None:
        response = requests.delete(
            f"{API_SERVER_URL}/admin/llm/provider/{self._provider_id}"
        )
        response.raise_for_status()


def seed_default_openai_provider() -> LLMProvider:
    llm = LLMProvider(
        provider="openai",
        default_model_name="gpt-4o-mini",
        api_key=os.environ["OPENAI_API_KEY"],
    )
    llm.create()
    return llm
