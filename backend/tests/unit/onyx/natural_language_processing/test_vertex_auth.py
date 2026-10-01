import json
from unittest.mock import MagicMock, patch

import pytest

from onyx.natural_language_processing.vertex_auth import (
    VertexEmbeddingConfig,
    resolve_vertex_embedding_credentials,
)


def test_workload_identity_uses_adc_and_explicit_target_project() -> None:
    credentials = MagicMock()
    config = VertexEmbeddingConfig(
        auth_method="workload_identity",
        project_id=" target-project ",
        location="us-central1",
    )
    with (
        patch(
            "google.auth.default", return_value=(credentials, "cluster-project")
        ) as adc,
        patch(
            "google.oauth2.service_account.Credentials.from_service_account_info"
        ) as key,
    ):
        resolved = resolve_vertex_embedding_credentials("unused-key", config)
    assert resolved == (credentials, "target-project", "us-central1")
    adc.assert_called_once_with(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    key.assert_not_called()


@pytest.mark.parametrize("project_id", [None, "", "   "])
def test_workload_identity_requires_project_before_adc_lookup(
    project_id: str | None,
) -> None:
    with patch("google.auth.default") as adc:
        with pytest.raises(ValueError, match="GCP Project ID is required"):
            resolve_vertex_embedding_credentials(
                None,
                VertexEmbeddingConfig(
                    auth_method="workload_identity", project_id=project_id
                ),
            )
    adc.assert_not_called()


def test_workload_identity_rejects_shared_deployment_credentials() -> None:
    with (
        patch("onyx.natural_language_processing.vertex_auth.MULTI_TENANT", True),
        patch("google.auth.default") as adc,
    ):
        with pytest.raises(ValueError, match="self-hosted"):
            resolve_vertex_embedding_credentials(
                None,
                VertexEmbeddingConfig(
                    auth_method="workload_identity", project_id="target-project"
                ),
            )
    adc.assert_not_called()


def test_service_account_preserves_json_project_and_location() -> None:
    credentials = MagicMock()
    with (
        patch(
            "google.oauth2.service_account.Credentials.from_service_account_info",
            return_value=credentials,
        ),
        patch("google.auth.default") as adc,
    ):
        resolved = resolve_vertex_embedding_credentials(
            '{"project_id":"key-project","location":"us-east1"}', None
        )
    assert resolved == (credentials, "key-project", "us-east1")
    adc.assert_not_called()


def test_service_account_does_not_implicitly_use_adc() -> None:
    with patch("google.auth.default") as adc:
        with pytest.raises(ValueError, match="Service account JSON is required"):
            resolve_vertex_embedding_credentials(None, None)
    adc.assert_not_called()


@pytest.mark.parametrize("auth_method", ["service_account_json", "workload_identity"])
@pytest.mark.parametrize("env_location", [None, "us-central1"])
def test_location_falls_back_to_environment_then_global(
    monkeypatch: pytest.MonkeyPatch, auth_method: str, env_location: str | None
) -> None:
    if env_location is None:
        monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    else:
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", env_location)
    credentials = MagicMock()
    config = (
        VertexEmbeddingConfig(
            auth_method="workload_identity", project_id="target-project"
        )
        if auth_method == "workload_identity"
        else None
    )
    with (
        patch("google.auth.default", return_value=(credentials, "cluster-project")),
        patch(
            "google.oauth2.service_account.Credentials.from_service_account_info",
            return_value=credentials,
        ),
    ):
        resolved = resolve_vertex_embedding_credentials(
            '{"project_id":"target-project"}', config
        )
    assert resolved == (credentials, "target-project", env_location or "global")


@pytest.mark.parametrize("project_id", [None, "", "   ", 123])
def test_service_account_rejects_invalid_project_id(
    project_id: str | int | None,
) -> None:
    with patch(
        "google.oauth2.service_account.Credentials.from_service_account_info"
    ) as key:
        with pytest.raises(ValueError, match="non-empty project_id"):
            resolve_vertex_embedding_credentials(
                json.dumps({"project_id": project_id}), None
            )
    key.assert_not_called()


@pytest.mark.parametrize("payload", ["[]", '{"project_id":"target","location":123}'])
def test_service_account_rejects_invalid_payload(payload: str) -> None:
    with patch(
        "google.oauth2.service_account.Credentials.from_service_account_info"
    ) as key:
        with pytest.raises(ValueError):
            resolve_vertex_embedding_credentials(payload, None)
    key.assert_not_called()
