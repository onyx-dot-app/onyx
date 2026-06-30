from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.image_gen.exceptions import ImageGenerationNotConfiguredError
from onyx.image_gen.generation import generate_images_with_default_config
from onyx.image_gen.generation import is_image_generation_configured
from onyx.image_gen.interfaces import ImageShape
from onyx.image_gen.interfaces import ReferenceImage

_HELPER = "onyx.image_gen.generation"


@pytest.fixture(autouse=True)
def _stub_session() -> object:
    with patch(f"{_HELPER}.get_session_with_current_tenant") as m:
        m.return_value.__enter__.return_value = MagicMock()
        yield m


def _fake_config(model_name: str, provider: str = "openai") -> SimpleNamespace:
    llm_provider = SimpleNamespace(
        provider=provider,
        api_key=None,
        api_base=None,
        api_version=None,
        deployment_name=None,
        custom_config=None,
    )
    model_configuration = SimpleNamespace(name=model_name, llm_provider=llm_provider)
    return SimpleNamespace(model_configuration=model_configuration)


def _img_item(b64: str, revised: str | None = None) -> MagicMock:
    item = MagicMock()
    dumped: dict[str, str] = {"b64_json": b64}
    if revised is not None:
        dumped["revised_prompt"] = revised
    item.model_dump.return_value = dumped
    return item


def _fake_provider(supports_ref: bool = True, data: list | None = None) -> MagicMock:
    provider = MagicMock()
    provider.supports_reference_images = supports_ref
    response = MagicMock()
    response.data = data if data is not None else [_img_item("aGVsbG8=", "revised")]
    provider.generate_image.return_value = response
    return provider


def test_no_default_config_raises() -> None:
    with patch(f"{_HELPER}.get_default_image_generation_config", return_value=None):
        with pytest.raises(ImageGenerationNotConfiguredError):
            generate_images_with_default_config(prompt="cat")


def test_invalid_credentials_raises() -> None:
    with (
        patch(
            f"{_HELPER}.get_default_image_generation_config",
            return_value=_fake_config("gpt-image-1"),
        ),
        patch(f"{_HELPER}.validate_credentials", return_value=False),
    ):
        with pytest.raises(ImageGenerationNotConfiguredError):
            generate_images_with_default_config(prompt="cat")


@pytest.mark.parametrize(
    "model,shape,expected_size",
    [
        ("gpt-image-1", ImageShape.SQUARE, "1024x1024"),
        ("gpt-image-1", ImageShape.LANDSCAPE, "1536x1024"),
        ("gpt-image-1", ImageShape.PORTRAIT, "1024x1536"),
        ("dall-e-3", ImageShape.LANDSCAPE, "1792x1024"),
        ("dall-e-3", ImageShape.PORTRAIT, "1024x1792"),
    ],
)
def test_size_mapping(model: str, shape: ImageShape, expected_size: str) -> None:
    provider = _fake_provider()
    with (
        patch(
            f"{_HELPER}.get_default_image_generation_config",
            return_value=_fake_config(model),
        ),
        patch(f"{_HELPER}.validate_credentials", return_value=True),
        patch(f"{_HELPER}.get_image_generation_provider", return_value=provider),
    ):
        generate_images_with_default_config(prompt="cat", shape=shape)

    kwargs = provider.generate_image.call_args.kwargs
    assert kwargs["size"] == expected_size
    if "gpt-image-" in model:
        assert kwargs["response_format"] is None
    else:
        assert kwargs["response_format"] == "b64_json"


def test_reference_images_unsupported_raises() -> None:
    provider = _fake_provider(supports_ref=False)
    refs = [ReferenceImage(data=b"x", mime_type="image/png")]
    with (
        patch(
            f"{_HELPER}.get_default_image_generation_config",
            return_value=_fake_config("gpt-image-1"),
        ),
        patch(f"{_HELPER}.validate_credentials", return_value=True),
        patch(f"{_HELPER}.get_image_generation_provider", return_value=provider),
    ):
        with pytest.raises(ValueError):
            generate_images_with_default_config(prompt="cat", reference_images=refs)


def test_returns_b64_and_revised_prompt() -> None:
    provider = _fake_provider(
        data=[_img_item("YWJj", "a revised prompt"), _img_item("ZGVm")]
    )
    with (
        patch(
            f"{_HELPER}.get_default_image_generation_config",
            return_value=_fake_config("gpt-image-1"),
        ),
        patch(f"{_HELPER}.validate_credentials", return_value=True),
        patch(f"{_HELPER}.get_image_generation_provider", return_value=provider),
    ):
        results = generate_images_with_default_config(prompt="my prompt", n=2)

    assert [r.b64_data for r in results] == ["YWJj", "ZGVm"]
    assert results[0].revised_prompt == "a revised prompt"
    assert results[1].revised_prompt == "my prompt"
    assert provider.generate_image.call_args.kwargs["n"] == 2


def test_no_image_data_raises() -> None:
    provider = _fake_provider(data=[])
    with (
        patch(
            f"{_HELPER}.get_default_image_generation_config",
            return_value=_fake_config("gpt-image-1"),
        ),
        patch(f"{_HELPER}.validate_credentials", return_value=True),
        patch(f"{_HELPER}.get_image_generation_provider", return_value=provider),
    ):
        with pytest.raises(RuntimeError):
            generate_images_with_default_config(prompt="cat")


def test_is_image_generation_configured_true() -> None:
    with (
        patch(
            f"{_HELPER}.get_default_image_generation_config",
            return_value=_fake_config("gpt-image-1"),
        ),
        patch(f"{_HELPER}.validate_credentials", return_value=True),
    ):
        assert is_image_generation_configured(MagicMock()) is True


def test_is_image_generation_configured_false_when_no_config() -> None:
    with patch(f"{_HELPER}.get_default_image_generation_config", return_value=None):
        assert is_image_generation_configured(MagicMock()) is False


def test_is_image_generation_configured_false_when_invalid_creds() -> None:
    with (
        patch(
            f"{_HELPER}.get_default_image_generation_config",
            return_value=_fake_config("gpt-image-1"),
        ),
        patch(f"{_HELPER}.validate_credentials", return_value=False),
    ):
        assert is_image_generation_configured(MagicMock()) is False
