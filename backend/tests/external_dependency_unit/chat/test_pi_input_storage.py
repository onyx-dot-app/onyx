"""Credential separation through real Redis admission and snapshot restore."""

import json
import zlib
from uuid import uuid4

import pytest

from onyx.cache.encryption import CacheValueCodec
from onyx.chat.pi.input_storage import (
    RunCredentials,
    RunInputSnapshot,
    load_run_inputs,
    save_run_inputs,
)
from onyx.chat.pi.inputs import RunInputs
from onyx.chat.pi.storage import TTL, load_state, run_key, session_key, state_redis
from onyx.db.models import AgentRun
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)
from shared_configs.contextvars import get_current_tenant_id


@pytest.fixture
def inputs() -> RunInputs:
    return RunInputs.model_validate(
        {
            "request": {
                "message": "ordinary user message",
                "mcp_headers": {"Authorization": "request-secret"},
            },
            "session_id": str(uuid4()),
            "user_id": str(uuid4()),
            "user_message_id": 1,
            "user_identity": {},
            "model": {
                "model_provider": "openai",
                "model_name": "test-model",
                "temperature": 0,
                "max_input_tokens": 8192,
                "api_key": "api-secret",
                "api_base": "https://example.test/?token=url-secret",
                "custom_config": {"vertex_credentials": "google-secret"},
            },
            "options": {
                "extra_headers": {"Authorization": "options-secret"},
                "temperature": 0,
            },
            "history": [],
            "context_files": {
                "context": {
                    "file_texts": [],
                    "image_files": [],
                    "use_as_search_filter": False,
                    "total_token_count": 0,
                    "file_metadata": [],
                    "uncapped_token_count": None,
                },
                "images": [],
            },
            "reasoning_effort": "auto",
            "search_params": {
                "project_id_filter": None,
                "persona_id_filter": None,
                "search_usage": "auto",
            },
            "file_metadata": {},
            "available_files": {},
            "forced_tool_id": None,
            "chat_files": [],
            "base_prompt": "ordinary system prompt",
            "system_prompt": None,
            "task_prompt": None,
            "replace_base_system_prompt": False,
            "datetime_aware": True,
            "custom_prompt": None,
            "memory": {"user_info": {}},
            "bypass_acl": False,
            "slack_context": None,
            "tool_headers": {"Authorization": "tool-secret"},
            "mcp_headers": {"Authorization": "mcp-secret"},
            "record_mode": None,
            "reserved_tokens": 0,
            "compression_window": 8192,
        }
    )


@pytest.mark.parametrize("edition", ["ce", "ee"])
def test_only_credentials_use_edition_encryption(
    inputs: RunInputs, edition: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    was_ee = global_version.is_ee_version()
    if edition == "ee":
        global_version.set_ee()
    else:
        global_version.unset_ee()
    fetch_versioned_implementation.cache_clear()
    monkeypatch.setattr(
        "onyx.cache.encryption.ENCRYPTION_KEY_SECRET",
        "pi-input-test-key-32-bytes-long!!!",
    )
    run_id = uuid4()
    run = AgentRun(id=run_id, chat_session_id=inputs.session_id)
    key, session = run_key(run_id, "inputs"), session_key(inputs.session_id)
    original = inputs.model_copy(deep=True)
    try:
        save_run_inputs(run_id, inputs.session_id, 1, inputs)
        raw = state_redis().get(key)
        assert isinstance(raw, bytes)
        document = json.loads(zlib.decompress(raw))
        ordinary = document["inputs"]
        assert ordinary["request"]["message"] == "ordinary user message"
        assert ordinary["base_prompt"] == "ordinary system prompt"
        assert "secret" not in json.dumps(ordinary)
        snapshot = load_state(run_id, "inputs", RunInputSnapshot)
        codec = CacheValueCodec(
            tenant_id=get_current_tenant_id(), purpose="agent-credentials"
        )
        credentials = RunCredentials.model_validate_json(
            codec.decode(key, snapshot.credentials)
        )
        assert credentials == RunCredentials(
            api_key=inputs.model.api_key,
            api_base=inputs.model.api_base,
            custom_config=inputs.model.custom_config,
            options=inputs.options,
            tool_headers=inputs.tool_headers,
            mcp_headers=inputs.mcp_headers,
            request_mcp_headers=inputs.request.mcp_headers,
        )
        if edition == "ce":
            # CE credentials remain recoverable without a secret key.
            json.loads(snapshot.credentials)
        else:
            with pytest.raises((ValueError, UnicodeDecodeError)):
                json.loads(snapshot.credentials)
        assert load_run_inputs(run) == original
        with pytest.raises(ValueError, match="do not belong"):
            load_run_inputs(AgentRun(id=run_id, chat_session_id=uuid4()))
        assert inputs == original
        ttl = state_redis().ttl(key)
        assert isinstance(ttl, int)
        assert 0 < ttl <= TTL
        del document["credentials"]
        state_redis().set(key, zlib.compress(json.dumps(document).encode()), ex=TTL)
        with pytest.raises(ValueError, match="Invalid agent checkpoint"):
            load_run_inputs(run)
        state_redis().delete(key)
        with pytest.raises(ValueError, match="expired"):
            load_run_inputs(run)
        # Rejected admission must not leave credential artifacts behind.
        state_redis().set(session + ":ended", "1", ex=60)
        with pytest.raises(ValueError, match="session has ended"):
            save_run_inputs(run_id, inputs.session_id, 1, inputs)
        assert not state_redis().exists(key)
    finally:
        state_redis().delete(key, session, session + ":ended")
        if was_ee:
            global_version.set_ee()
        else:
            global_version.unset_ee()
        fetch_versioned_implementation.cache_clear()
