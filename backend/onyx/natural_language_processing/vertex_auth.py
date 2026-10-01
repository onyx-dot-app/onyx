import json
import os
from typing import Literal

import google.auth
from google.auth.credentials import Credentials
from google.oauth2 import service_account
from pydantic import BaseModel, ConfigDict

from shared_configs.configs import MULTI_TENANT


class VertexEmbeddingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auth_method: Literal["service_account_json", "workload_identity"] = (
        "service_account_json"
    )
    project_id: str | None = None
    location: str | None = None


def validate_vertex_embedding_config(config: VertexEmbeddingConfig | None) -> None:
    if config is None or config.auth_method != "workload_identity":
        return
    if MULTI_TENANT:
        raise ValueError(
            "Workload Identity is only available for self-hosted deployments."
        )
    if not config.project_id or not config.project_id.strip():
        raise ValueError("GCP Project ID is required for Workload Identity.")


def resolve_vertex_embedding_credentials(
    api_key: str | None, config: VertexEmbeddingConfig | None
) -> tuple[Credentials, str, str]:
    validate_vertex_embedding_config(config)
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    location = config.location.strip() if config and config.location else None
    if config and config.auth_method == "workload_identity":
        # Use the configured target project, which can differ from the pod's project.
        if config.project_id is None:
            raise ValueError("GCP Project ID is required for Workload Identity.")
        credentials, _ = google.auth.default(scopes=scopes)
        project_id = config.project_id.strip()
    else:
        if not api_key:
            raise ValueError("Service account JSON is required for Google embeddings.")
        service_account_info = json.loads(api_key)
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info, scopes=scopes
        )
        project_id = service_account_info["project_id"]
        location = location or service_account_info.get("location")
    return (
        credentials,
        project_id,
        location or os.environ.get("GOOGLE_CLOUD_LOCATION") or "global",
    )
