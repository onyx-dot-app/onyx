"""Keep connection credentials separate from ordinary chat state at rest."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from onyx.cache.encryption import CacheValueCodec
from onyx.chat.pi.inputs import RunInputs
from onyx.chat.pi.storage import load_state, run_key, save_inputs
from onyx.db.models import AgentRun
from shared_configs.contextvars import get_current_tenant_id


class RunCredentials(BaseModel):
    api_key: str | None
    api_base: str | None
    custom_config: dict[str, str] | None
    # Provider extensions can contain credentials under arbitrary keys.
    options: dict[str, Any]
    tool_headers: dict[str, str] | None
    mcp_headers: dict[str, str] | None
    request_mcp_headers: dict[str, str] | None


class RunInputSnapshot(BaseModel):
    # Only the credential blob needs binary-to-JSON encoding.
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    inputs: RunInputs
    credentials: bytes = Field(repr=False)


def _credential_codec() -> CacheValueCodec:
    return CacheValueCodec(
        tenant_id=get_current_tenant_id(), purpose="agent-credentials"
    )


def save_run_inputs(
    run_id: UUID, session_id: UUID, group_id: int, inputs: RunInputs
) -> None:
    credentials = RunCredentials(
        api_key=inputs.model.api_key,
        api_base=inputs.model.api_base,
        custom_config=inputs.model.custom_config,
        options=inputs.options,
        tool_headers=inputs.tool_headers,
        mcp_headers=inputs.mcp_headers,
        request_mcp_headers=inputs.request.mcp_headers,
    )
    ordinary_inputs = inputs.model_copy(
        update={
            "model": inputs.model.model_copy(
                update={"api_key": None, "api_base": None, "custom_config": None}
            ),
            "options": {},
            "tool_headers": None,
            "mcp_headers": None,
            "request": inputs.request.model_copy(update={"mcp_headers": None}),
        }
    )
    snapshot = RunInputSnapshot(
        inputs=ordinary_inputs,
        credentials=_credential_codec().encode(
            run_key(run_id, "inputs"), credentials.model_dump_json().encode()
        ),
    )
    # One record preserves admission, expiration, and teardown atomicity.
    save_inputs(run_id, session_id, group_id, snapshot)


def load_run_inputs(run: AgentRun) -> RunInputs:
    run_id = run.id
    snapshot = load_state(run_id, "inputs", RunInputSnapshot)
    if snapshot.inputs.session_id != run.chat_session_id:
        raise ValueError("Agent inputs do not belong to this run's session")
    raw = _credential_codec().decode(run_key(run_id, "inputs"), snapshot.credentials)
    try:
        credentials = RunCredentials.model_validate_json(raw)
    except ValidationError:
        raise ValueError("Invalid agent credentials") from None
    inputs = snapshot.inputs
    return inputs.model_copy(
        update={
            "model": inputs.model.model_copy(
                update={
                    "api_key": credentials.api_key,
                    "api_base": credentials.api_base,
                    "custom_config": credentials.custom_config,
                }
            ),
            "options": credentials.options,
            "tool_headers": credentials.tool_headers,
            "mcp_headers": credentials.mcp_headers,
            "request": inputs.request.model_copy(
                update={"mcp_headers": credentials.request_mcp_headers}
            ),
        }
    )
