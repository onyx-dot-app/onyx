from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import httpx

from onyx.server.security.models import outbound_ssrf_params
from onyx.server.security.store import get_security_settings
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call
from onyx.utils.url import validate_outbound_http_url
from onyx.voice.audio_utils import audio_bytes_to_file
from onyx.voice.interface import VoiceProviderInterface
from onyx.voice.types import VoiceProviderType

if TYPE_CHECKING:
    from openai import AsyncOpenAI


def normalize_openai_compatible_api_base(api_base: str) -> str:
    url = httpx.URL(api_base)
    path = url.path.rstrip("/")
    normalized_path = path if path.endswith("/v1") else f"{path}/v1"
    return str(url.copy_with(path=normalized_path))


def validate_openai_compatible_url(url: str) -> str:
    params = outbound_ssrf_params(get_security_settings().ssrf_protection_level)
    return validate_outbound_http_url(
        url,
        allow_private_network=params.allow_private_network,
        block_loopback_and_link_local=params.block_loopback_and_link_local,
        block_link_local_only=params.block_link_local_only,
    )


class _SSRFGuardAsyncTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        validate_openai_compatible_url(str(request.url))
        return await super().handle_async_request(request)


class OpenAICompatibleVoiceProvider(VoiceProviderInterface):
    def __init__(self, api_base: str, stt_model: str, api_key: str | None = None):
        self.api_base = normalize_openai_compatible_api_base(api_base)
        self.stt_model = stt_model
        self.api_key = api_key
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> "AsyncOpenAI":
        if self._client is None:
            from openai import AsyncOpenAI, DefaultAsyncHttpxClient

            self._client = AsyncOpenAI(
                api_key=self.api_key or "",
                base_url=self.api_base,
                http_client=DefaultAsyncHttpxClient(
                    transport=_SSRFGuardAsyncTransport()
                ),
                _enforce_credentials=False,
                _strict_response_validation=True,
            )
        return self._client

    async def transcribe(self, audio_data: bytes, audio_format: str) -> str:
        audio_file = audio_bytes_to_file(audio_data, audio_format)
        with traced_llm_call(
            flow=LLMFlow.STT,
            model=self.stt_model,
            provider=VoiceProviderType.OPENAI_COMPATIBLE.value,
        ):
            response = await self._get_client().audio.transcriptions.create(
                model=self.stt_model,
                file=audio_file,
            )
        return response.text

    def synthesize_stream(
        self, text: str, voice: str | None = None, speed: float = 1.0
    ) -> AsyncIterator[bytes]:
        raise NotImplementedError("OpenAI-compatible voice providers are STT-only.")

    async def validate_credentials(self) -> None:
        from openai import (
            APIConnectionError,
            APIResponseValidationError,
            APIStatusError,
            AuthenticationError,
            PermissionDeniedError,
        )

        try:
            models = await self._get_client().models.list()
        except AuthenticationError as exc:
            raise ValueError("The endpoint rejected the API key.") from exc
        except PermissionDeniedError as exc:
            raise ValueError("The API key cannot list endpoint models.") from exc
        except APIConnectionError as exc:
            raise ValueError("Could not reach the speech-to-text endpoint.") from exc
        except APIResponseValidationError as exc:
            raise ValueError(
                "The endpoint returned an invalid models response."
            ) from exc
        except APIStatusError as exc:
            raise ValueError(
                f"The endpoint model request failed with status {exc.status_code}."
            ) from exc

        if self.stt_model not in {model.id for model in models.data}:
            raise ValueError(
                f"Speech-to-text model '{self.stt_model}' is not available."
            )

    def get_available_voices(self) -> list[dict[str, str]]:
        return []

    def get_available_stt_models(self) -> list[dict[str, str]]:
        return []

    def get_available_tts_models(self) -> list[dict[str, str]]:
        return []

    def supports_streaming_stt(self) -> bool:
        return False
