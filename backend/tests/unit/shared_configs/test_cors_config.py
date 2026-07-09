import pytest

from shared_configs.configs import cors_allow_credentials
from shared_configs.configs import parse_cors_allowed_origins


def test_empty_env_allows_all_origins_without_credentials() -> None:
    origins = parse_cors_allowed_origins("")
    assert origins == ["*"]
    assert cors_allow_credentials(origins) is False


def test_explicit_wildcard_disables_credentials() -> None:
    origins = parse_cors_allowed_origins("*")
    assert origins == ["*"]
    assert cors_allow_credentials(origins) is False


def test_single_origin_keeps_credentials() -> None:
    origins = parse_cors_allowed_origins("http://localhost:3000")
    assert origins == ["http://localhost:3000"]
    assert cors_allow_credentials(origins) is True


def test_multiple_origins_parsed_and_stripped() -> None:
    origins = parse_cors_allowed_origins(
        " https://onyx.example.com , http://localhost:3000 ,"
    )
    assert origins == ["https://onyx.example.com", "http://localhost:3000"]
    assert cors_allow_credentials(origins) is True


def test_wildcard_mixed_with_explicit_origins_disables_credentials() -> None:
    origins = parse_cors_allowed_origins("https://onyx.example.com,*")
    assert origins == ["https://onyx.example.com", "*"]
    assert cors_allow_credentials(origins) is False


def test_invalid_origin_rejected() -> None:
    with pytest.raises(ValueError):
        parse_cors_allowed_origins("not-a-url")
