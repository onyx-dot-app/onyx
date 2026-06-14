# Platform Default OpenAI-Compatible LLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current consumer model profile system with a minimal Onyx-native platform default `openai_compatible` LLM provider seed configured by API base URL, API key, and one main model name.

**Architecture:** Keep Onyx's existing `LLMProvider` / `ModelConfiguration` / default `LLMModelFlow` architecture as the only runtime source of truth. The seed path creates or updates one managed `openai_compatible` provider, then chat, deep research, title generation, and Craft fall back to existing default-model resolution instead of consumer profiles.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, Pydantic, pytest, Next.js 15, React 18, TypeScript, SWR.

---

## Issues To Address

- Current implementation exposes model profile product surface (`/api/model-catalog`, `/api/user/model-preference`, `ConsumerModelProfileSelector`) that the product does not want.
- Seed logic currently creates five Qwen profile models instead of one platform-configured main model.
- Runtime paths force scenario-specific consumer profiles for ordinary chat, deep research, title generation, and Craft.
- `.vscode/.env`, `summary.md`, and product docs must reflect the final minimal configuration.

## Important Notes

- Do not add a database migration.
- Do not add a new provider type.
- Do not expose API base URL or API key to the frontend.
- Preserve any existing extra model configurations on the managed provider so `upsert_llm_provider()` does not delete administrator-created rows.
- Do not touch the untracked root-level `coding_agent_tool.py`.
- Windows verification should use `PYTHONUTF8=1` and `.venv\Scripts\python.exe -m pytest`.

## File Structure

- Modify `backend/onyx/configs/app_configs.py`: replace profile/provider envs with the minimal main-model env and fixed internal provider constants.
- Modify `backend/onyx/db/consumer_llm.py`: make the seed module the single owner of platform default LLM config and idempotent provider upsert behavior.
- Modify `backend/tests/unit/onyx/db/test_consumer_llm.py`: rewrite seed tests for one model and default overwrite rules.
- Delete `backend/onyx/llm/consumer_model_catalog.py`: remove profile catalog runtime.
- Delete `backend/onyx/server/manage/consumer_models_api.py`: remove profile/preference API.
- Modify `backend/onyx/main.py`: remove consumer model router import and registration.
- Modify `backend/onyx/chat/process_message.py`: remove consumer profile override resolution.
- Modify `backend/onyx/llm/factory.py`: remove `get_llm_for_consumer_model_profile()`.
- Modify `backend/onyx/server/query_and_chat/chat_backend.py`: title generation uses `get_default_llm()`.
- Modify `backend/onyx/server/features/build/session/llm_config.py`: remove Craft consumer profile preference.
- Delete backend tests for removed catalog/API modules.
- Modify `web/src/refresh-pages/AppPage.tsx` and `web/src/app/nrf/NRFPage.tsx`: remove consumer model selector import and rendering.
- Delete `web/src/refresh-components/popovers/ConsumerModelProfileSelector.tsx`, `web/src/hooks/useConsumerModelCatalog.ts`, and `web/src/lib/consumerModels/*`.
- Modify `web/src/lib/swr-keys.ts`: remove consumer model SWR keys.
- Modify `.vscode/.env`: replace old profile envs with `CONSUMER_DEFAULT_LLM_MODEL_NAME`.
- Modify `summary.md`: record implementation details, tests, and any pitfalls.

---

### Task 1: Rewrite Platform Default Seed Tests

**Files:**
- Modify: `backend/tests/unit/onyx/db/test_consumer_llm.py`
- Modify: `backend/onyx/db/consumer_llm.py`
- Modify: `backend/onyx/configs/app_configs.py`

- [ ] **Step 1: Replace seed tests with one-model expectations**

Replace `backend/tests/unit/onyx/db/test_consumer_llm.py` with focused tests for the new behavior:

```python
from types import SimpleNamespace
from unittest.mock import Mock

from onyx.db.consumer_llm import ConsumerDefaultLLMConfig
from onyx.db.consumer_llm import build_consumer_llm_provider_request
from onyx.db.consumer_llm import seed_consumer_default_llm_provider


def _config(**overrides: object) -> ConsumerDefaultLLMConfig:
    values = {
        "enabled": True,
        "api_base": "https://example.test/v1",
        "api_key": "test-key",
        "model_name": "qwen-plus",
        "auto_provision_enabled": True,
    }
    values.update(overrides)
    return ConsumerDefaultLLMConfig(**values)


def test_build_consumer_llm_provider_request_uses_single_main_model() -> None:
    request = build_consumer_llm_provider_request(_config())

    assert request.name == "Glomi Default"
    assert request.provider == "openai_compatible"
    assert request.api_base == "https://example.test/v1"
    assert request.api_key == "test-key"
    assert request.api_key_changed is True
    assert request.is_public is True
    assert request.is_auto_mode is False
    assert [model.name for model in request.model_configurations] == ["qwen-plus"]
    assert request.model_configurations[0].is_visible is True


def test_seed_skips_when_disabled() -> None:
    result = seed_consumer_default_llm_provider(Mock(), _config(enabled=False))

    assert result.seeded is False
    assert result.reason == "disabled"


def test_seed_skips_when_auto_provisioning_disabled() -> None:
    result = seed_consumer_default_llm_provider(
        Mock(), _config(auto_provision_enabled=False)
    )

    assert result.seeded is False
    assert result.reason == "auto_provision_disabled"


def test_seed_skips_when_api_key_missing() -> None:
    result = seed_consumer_default_llm_provider(Mock(), _config(api_key=None))

    assert result.seeded is False
    assert result.reason == "missing_api_key"


def test_seed_skips_when_api_base_missing() -> None:
    result = seed_consumer_default_llm_provider(Mock(), _config(api_base=""))

    assert result.seeded is False
    assert result.reason == "missing_api_base"


def test_seed_skips_when_model_name_missing() -> None:
    result = seed_consumer_default_llm_provider(Mock(), _config(model_name=""))

    assert result.seeded is False
    assert result.reason == "missing_model_name"


def test_seed_upserts_provider_and_sets_default_when_missing(monkeypatch) -> None:
    upsert_llm_provider = Mock(return_value=SimpleNamespace(id=7))
    update_default_provider = Mock()

    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_existing_llm_provider_by_name_and_type",
        Mock(return_value=None),
    )
    monkeypatch.setattr("onyx.db.consumer_llm.upsert_llm_provider", upsert_llm_provider)
    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_default_llm_model", Mock(return_value=None)
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.update_default_provider", update_default_provider
    )

    db_session = Mock()
    result = seed_consumer_default_llm_provider(db_session, _config())

    request = upsert_llm_provider.call_args.args[0]
    assert result.seeded is True
    assert result.reason == "seeded"
    assert request.id is None
    update_default_provider.assert_called_once_with(7, "qwen-plus", db_session)


def test_seed_preserves_existing_extra_models(monkeypatch) -> None:
    existing_provider = SimpleNamespace(
        id=7,
        model_configurations=[
            SimpleNamespace(
                name="legacy-model",
                is_visible=True,
                max_input_tokens=1234,
                supports_image_input=False,
                display_name="Legacy Model",
                custom_display_name=None,
                llm_model_flow_types=[],
            )
        ],
    )
    upsert_llm_provider = Mock(return_value=SimpleNamespace(id=7))

    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_existing_llm_provider_by_name_and_type",
        Mock(return_value=existing_provider),
    )
    monkeypatch.setattr("onyx.db.consumer_llm.upsert_llm_provider", upsert_llm_provider)
    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_default_llm_model", Mock(return_value=None)
    )
    monkeypatch.setattr("onyx.db.consumer_llm.update_default_provider", Mock())

    seed_consumer_default_llm_provider(Mock(), _config())

    request = upsert_llm_provider.call_args.args[0]
    assert request.id == 7
    assert {model.name for model in request.model_configurations} == {
        "qwen-plus",
        "legacy-model",
    }
    legacy = next(
        model for model in request.model_configurations if model.name == "legacy-model"
    )
    assert legacy.is_visible is True
    assert legacy.max_input_tokens == 1234


def test_seed_updates_default_when_current_default_is_same_provider(
    monkeypatch,
) -> None:
    existing_provider = SimpleNamespace(id=7, model_configurations=[])
    current_default = SimpleNamespace(llm_provider_id=7, name="old-main-model")
    update_default_provider = Mock()

    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_existing_llm_provider_by_name_and_type",
        Mock(return_value=existing_provider),
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.upsert_llm_provider",
        Mock(return_value=SimpleNamespace(id=7)),
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_default_llm_model",
        Mock(return_value=current_default),
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.update_default_provider", update_default_provider
    )

    seed_consumer_default_llm_provider(Mock(), _config(model_name="qwen-max"))

    update_default_provider.assert_called_once()
    assert update_default_provider.call_args.args[1] == "qwen-max"


def test_seed_does_not_override_other_provider_default(monkeypatch) -> None:
    existing_provider = SimpleNamespace(id=7, model_configurations=[])
    current_default = SimpleNamespace(llm_provider_id=99, name="admin-model")
    update_default_provider = Mock()

    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_existing_llm_provider_by_name_and_type",
        Mock(return_value=existing_provider),
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.upsert_llm_provider",
        Mock(return_value=SimpleNamespace(id=7)),
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.fetch_default_llm_model",
        Mock(return_value=current_default),
    )
    monkeypatch.setattr(
        "onyx.db.consumer_llm.update_default_provider", update_default_provider
    )

    seed_consumer_default_llm_provider(Mock(), _config(model_name="qwen-max"))

    update_default_provider.assert_not_called()
```

- [ ] **Step 2: Run the seed tests and verify they fail**

Run:

```powershell
$env:PYTHONUTF8='1'; .venv\Scripts\python.exe -m pytest backend/tests/unit/onyx/db/test_consumer_llm.py -q
```

Expected: failures because `ConsumerDefaultLLMConfig` still has profile/provider fields and seed still builds catalog models.

- [ ] **Step 3: Add minimal config constants**

In `backend/onyx/configs/app_configs.py`, replace the old consumer profile env block with:

```python
CONSUMER_DEFAULT_LLM_ENABLED = (
    os.environ.get("CONSUMER_DEFAULT_LLM_ENABLED", "false").lower() == "true"
)
CONSUMER_DEFAULT_LLM_PROVIDER_NAME = "Glomi Default"
CONSUMER_DEFAULT_LLM_PROVIDER_TYPE = "openai_compatible"
CONSUMER_DEFAULT_LLM_API_BASE = os.environ.get("CONSUMER_DEFAULT_LLM_API_BASE")
CONSUMER_DEFAULT_LLM_API_KEY = os.environ.get("CONSUMER_DEFAULT_LLM_API_KEY")
CONSUMER_DEFAULT_LLM_MODEL_NAME = os.environ.get("CONSUMER_DEFAULT_LLM_MODEL_NAME")
```

- [ ] **Step 4: Implement one-model seed logic**

In `backend/onyx/db/consumer_llm.py`, remove `consumer_model_catalog`, vision default, and profile imports. Implement these shapes:

```python
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from onyx.configs.app_configs import AUTO_PROVISION_DEFAULT_LLM_PROVIDERS
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_API_BASE
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_API_KEY
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_ENABLED
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_MODEL_NAME
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_PROVIDER_NAME
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_PROVIDER_TYPE
from onyx.db.llm import fetch_default_llm_model
from onyx.db.llm import fetch_existing_llm_provider_by_name_and_type
from onyx.db.llm import update_default_provider
from onyx.db.llm import upsert_llm_provider
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.utils.logger import setup_logger

logger = setup_logger()


@dataclass(frozen=True)
class ConsumerDefaultLLMConfig:
    enabled: bool
    api_base: str | None
    api_key: str | None
    model_name: str | None
    auto_provision_enabled: bool


@dataclass(frozen=True)
class ConsumerDefaultLLMSeedResult:
    seeded: bool
    reason: str


def get_consumer_default_llm_config() -> ConsumerDefaultLLMConfig:
    return ConsumerDefaultLLMConfig(
        enabled=CONSUMER_DEFAULT_LLM_ENABLED,
        api_base=CONSUMER_DEFAULT_LLM_API_BASE,
        api_key=CONSUMER_DEFAULT_LLM_API_KEY,
        model_name=CONSUMER_DEFAULT_LLM_MODEL_NAME,
        auto_provision_enabled=AUTO_PROVISION_DEFAULT_LLM_PROVIDERS,
    )
```

Then implement request building and seed behavior:

```python
def _model_config_from_existing(model_configuration: object) -> ModelConfigurationUpsertRequest:
    return ModelConfigurationUpsertRequest(
        name=model_configuration.name,
        is_visible=model_configuration.is_visible,
        max_input_tokens=model_configuration.max_input_tokens,
        supports_image_input=model_configuration.supports_image_input,
        display_name=model_configuration.display_name,
        custom_display_name=model_configuration.custom_display_name,
    )


def build_consumer_llm_provider_request(
    config: ConsumerDefaultLLMConfig,
) -> LLMProviderUpsertRequest:
    if not config.model_name:
        raise ValueError("model_name is required to build provider request")

    return LLMProviderUpsertRequest(
        name=CONSUMER_DEFAULT_LLM_PROVIDER_NAME,
        provider=CONSUMER_DEFAULT_LLM_PROVIDER_TYPE,
        api_key=config.api_key,
        api_base=config.api_base,
        api_key_changed=True,
        is_public=True,
        is_auto_mode=False,
        model_configurations=[
            ModelConfigurationUpsertRequest(
                name=config.model_name,
                is_visible=True,
                max_input_tokens=None,
            )
        ],
    )
```

```python
def _should_update_default_model(
    current_default: object | None,
    provider_id: int,
    model_name: str,
) -> bool:
    if current_default is None:
        return True

    return (
        getattr(current_default, "llm_provider_id", None) == provider_id
        and getattr(current_default, "name", None) != model_name
    )


def seed_consumer_default_llm_provider(
    db_session: Session,
    config: ConsumerDefaultLLMConfig | None = None,
) -> ConsumerDefaultLLMSeedResult:
    config = config or get_consumer_default_llm_config()
    if not config.enabled:
        logger.info("Skipping consumer default LLM provider seed: disabled")
        return ConsumerDefaultLLMSeedResult(seeded=False, reason="disabled")

    if not config.auto_provision_enabled:
        logger.info(
            "Skipping consumer default LLM provider seed: auto provisioning disabled"
        )
        return ConsumerDefaultLLMSeedResult(
            seeded=False, reason="auto_provision_disabled"
        )

    if not config.api_key:
        logger.warning(
            "Skipping consumer default LLM provider seed: "
            "CONSUMER_DEFAULT_LLM_API_KEY is unset"
        )
        return ConsumerDefaultLLMSeedResult(seeded=False, reason="missing_api_key")

    if not config.api_base:
        logger.warning(
            "Skipping consumer default LLM provider seed: "
            "CONSUMER_DEFAULT_LLM_API_BASE is unset"
        )
        return ConsumerDefaultLLMSeedResult(seeded=False, reason="missing_api_base")

    if not config.model_name:
        logger.warning(
            "Skipping consumer default LLM provider seed: "
            "CONSUMER_DEFAULT_LLM_MODEL_NAME is unset"
        )
        return ConsumerDefaultLLMSeedResult(seeded=False, reason="missing_model_name")

    request = build_consumer_llm_provider_request(config)
    existing_provider = fetch_existing_llm_provider_by_name_and_type(
        name=CONSUMER_DEFAULT_LLM_PROVIDER_NAME,
        provider_type=CONSUMER_DEFAULT_LLM_PROVIDER_TYPE,
        db_session=db_session,
    )
    if existing_provider:
        request.id = existing_provider.id
        requested_names = {model.name for model in request.model_configurations}
        for existing_model_config in existing_provider.model_configurations:
            if existing_model_config.name in requested_names:
                continue
            request.model_configurations.append(
                _model_config_from_existing(existing_model_config)
            )

    provider = upsert_llm_provider(request, db_session)
    current_default = fetch_default_llm_model(db_session)
    if _should_update_default_model(current_default, provider.id, config.model_name):
        update_default_provider(provider.id, config.model_name, db_session)

    return ConsumerDefaultLLMSeedResult(seeded=True, reason="seeded")
```

- [ ] **Step 5: Run seed tests and verify they pass**

Run:

```powershell
$env:PYTHONUTF8='1'; .venv\Scripts\python.exe -m pytest backend/tests/unit/onyx/db/test_consumer_llm.py -q
```

Expected: all tests in `test_consumer_llm.py` pass.

- [ ] **Step 6: Commit seed changes**

Run:

```powershell
git add backend/onyx/configs/app_configs.py backend/onyx/db/consumer_llm.py backend/tests/unit/onyx/db/test_consumer_llm.py
git commit -m "feat: seed platform default llm provider"
```

---

### Task 2: Remove Consumer Profile Runtime Overrides

**Files:**
- Modify: `backend/onyx/chat/process_message.py`
- Modify: `backend/onyx/llm/factory.py`
- Modify: `backend/onyx/server/query_and_chat/chat_backend.py`
- Modify: `backend/onyx/server/features/build/session/llm_config.py`
- Delete: `backend/tests/unit/onyx/test_consumer_model_catalog.py`
- Modify/Delete tests that refer to Craft consumer profile behavior

- [ ] **Step 1: Run current consumer-profile test search**

Run:

```powershell
rg -n "consumer_model_catalog|get_llm_for_consumer_model_profile|ConsumerModelProfile|CRAFT_CONSUMER|TITLE_CONSUMER|resolve_single_model_profile_id" backend
```

Expected: matches in runtime and tests that must be removed in this task.

- [ ] **Step 2: Remove chat profile override resolution**

In `backend/onyx/chat/process_message.py`, delete these imports:

```python
from onyx.llm.consumer_model_catalog import get_consumer_model_profile
from onyx.llm.consumer_model_catalog import profile_to_llm_override
from onyx.llm.consumer_model_catalog import resolve_single_model_profile_id
```

Delete `_resolve_single_model_llm_override()`.

Replace the single-model override selection block with:

```python
    selected_overrides: list[LLMOverride | None] = (
        list(llm_overrides or [])
        if is_multi
        else [new_msg_req.llm_override or chat_session.llm_override]
    )
```

- [ ] **Step 3: Remove factory helper**

In `backend/onyx/llm/factory.py`, delete:

```python
from onyx.db.llm import fetch_existing_llm_provider_by_name_and_type
from onyx.llm.consumer_model_catalog import get_consumer_model_profile
```

Then delete the full `get_llm_for_consumer_model_profile()` function. Keep `_resolve_provider_type_override()` because existing explicit override fallback still uses it.

- [ ] **Step 4: Simplify title generation model selection**

In `backend/onyx/server/query_and_chat/chat_backend.py`, delete:

```python
from onyx.llm.consumer_model_catalog import TITLE_CONSUMER_MODEL_PROFILE_ID
from onyx.llm.factory import get_llm_for_consumer_model_profile
```

Replace the title generation LLM block with:

```python
    llm = get_default_llm(additional_headers=additional_headers)
```

- [ ] **Step 5: Remove Craft profile preference**

In `backend/onyx/server/features/build/session/llm_config.py`, delete:

```python
from onyx.llm.consumer_model_catalog import CRAFT_CONSUMER_MODEL_PROFILE_ID
from onyx.llm.consumer_model_catalog import get_consumer_model_profile
```

Delete `_visible_model_names()` and `_consumer_craft_default_config()`.

Remove this branch from `select_default_llm_config()`:

```python
    consumer_default = _consumer_craft_default_config(providers)
    if consumer_default is not None:
        return consumer_default
```

- [ ] **Step 6: Remove profile catalog unit tests**

Delete:

```powershell
git rm backend/tests/unit/onyx/test_consumer_model_catalog.py
```

If `backend/tests/unit/onyx/server/features/build/session/test_get_all_build_mode_llm_configs.py` contains tests named around `consumer_coding_profile`, remove or rewrite them to assert the existing provider-priority fallback. Use this expected assertion shape:

```python
assert result.provider == providers[0].provider
assert result.model_name in {model.name for model in providers[0].model_configurations}
```

- [ ] **Step 7: Verify runtime imports no longer reference catalog**

Run:

```powershell
rg -n "consumer_model_catalog|get_llm_for_consumer_model_profile|CRAFT_CONSUMER|TITLE_CONSUMER|resolve_single_model_profile_id" backend
```

Expected: no runtime matches. Test-only matches should be removed before continuing.

- [ ] **Step 8: Run focused backend tests**

Run:

```powershell
$env:PYTHONUTF8='1'; .venv\Scripts\python.exe -m pytest backend/tests/unit/onyx/db/test_consumer_llm.py backend/tests/unit/onyx/server/features/build/session/test_get_all_build_mode_llm_configs.py -q
```

Expected: selected tests pass.

- [ ] **Step 9: Commit runtime cleanup**

Run:

```powershell
git add backend/onyx/chat/process_message.py backend/onyx/llm/factory.py backend/onyx/server/query_and_chat/chat_backend.py backend/onyx/server/features/build/session/llm_config.py backend/tests/unit/onyx
git commit -m "refactor: use default llm instead of consumer profiles"
```

---

### Task 3: Remove Consumer Model API And Frontend Selector

**Files:**
- Modify: `backend/onyx/main.py`
- Delete: `backend/onyx/server/manage/consumer_models_api.py`
- Delete: `backend/tests/unit/onyx/server/manage/test_consumer_models_api.py`
- Delete: `backend/onyx/llm/consumer_model_catalog.py`
- Modify: `web/src/refresh-pages/AppPage.tsx`
- Modify: `web/src/app/nrf/NRFPage.tsx`
- Modify: `web/src/lib/swr-keys.ts`
- Delete: `web/src/refresh-components/popovers/ConsumerModelProfileSelector.tsx`
- Delete: `web/src/hooks/useConsumerModelCatalog.ts`
- Delete: `web/src/lib/consumerModels/types.ts`
- Delete: `web/src/lib/consumerModels/svc.ts`
- Delete: `web/src/lib/consumerModels/utils.ts`
- Delete: `web/src/lib/consumerModels/utils.test.ts`

- [ ] **Step 1: Remove backend router registration**

In `backend/onyx/main.py`, delete:

```python
from onyx.server.manage.consumer_models_api import router as consumer_models_router
```

And delete:

```python
    include_router_with_global_prefix_prepended(application, consumer_models_router)
```

- [ ] **Step 2: Delete backend catalog/API files and tests**

Run:

```powershell
git rm backend/onyx/server/manage/consumer_models_api.py
git rm backend/onyx/llm/consumer_model_catalog.py
git rm backend/tests/unit/onyx/server/manage/test_consumer_models_api.py
```

- [ ] **Step 3: Remove AppPage selector usage**

In `web/src/refresh-pages/AppPage.tsx`, delete:

```typescript
import ConsumerModelProfileSelector from "@/refresh-components/popovers/ConsumerModelProfileSelector";
```

Delete both `<ConsumerModelProfileSelector />` render blocks. In the welcome section, leave `WelcomeMessage` inside the existing `Section`. In the input-bar section, remove the surrounding `div` that only existed for the selector.

- [ ] **Step 4: Remove NRF selector usage**

In `web/src/app/nrf/NRFPage.tsx`, delete:

```typescript
import ConsumerModelProfileSelector from "@/refresh-components/popovers/ConsumerModelProfileSelector";
```

Delete both `<ConsumerModelProfileSelector />` render blocks. Keep the existing `WelcomeMessage`, `Spacer`, and `AppInputBar` layout.

- [ ] **Step 5: Delete frontend selector modules**

Run:

```powershell
git rm web/src/refresh-components/popovers/ConsumerModelProfileSelector.tsx
git rm web/src/hooks/useConsumerModelCatalog.ts
git rm web/src/lib/consumerModels/types.ts
git rm web/src/lib/consumerModels/svc.ts
git rm web/src/lib/consumerModels/utils.ts
git rm web/src/lib/consumerModels/utils.test.ts
```

- [ ] **Step 6: Remove SWR keys**

In `web/src/lib/swr-keys.ts`, delete:

```typescript
  consumerModelCatalog: "/api/model-catalog",
  consumerModelPreference: "/api/user/model-preference",
```

- [ ] **Step 7: Verify consumer model product surface is gone**

Run:

```powershell
rg -n "model-catalog|model-preference|ConsumerModelProfileSelector|useConsumerModelCatalog|consumerModels|consumer_model_catalog" backend web
```

Expected: no matches except historical docs or summary if the command is expanded beyond `backend web`.

- [ ] **Step 8: Verify app startup route auth**

Run:

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONPATH='backend'; .venv\Scripts\python.exe -c "from onyx.main import get_application; get_application(lifespan_override=lambda app: None); print('app-ok')"
```

Expected: prints `app-ok` and no `/model-catalog` route auth error.

- [ ] **Step 9: Run frontend typecheck**

Run:

```powershell
cd web
npm run types:check
```

Expected: TypeScript passes. If `npm` reports missing dependencies, run the repo's existing frontend install flow before retrying; do not use `bun` on this machine.

- [ ] **Step 10: Commit API/UI removal**

Run:

```powershell
git add backend/onyx/main.py web/src/refresh-pages/AppPage.tsx web/src/app/nrf/NRFPage.tsx web/src/lib/swr-keys.ts
git add -u backend/onyx/server/manage backend/onyx/llm backend/tests/unit/onyx/server/manage web/src/refresh-components/popovers web/src/hooks web/src/lib/consumerModels
git commit -m "refactor: remove consumer model selector surface"
```

---

### Task 4: Update Local Env, Docs, And Final Verification

**Files:**
- Modify: `.vscode/.env`
- Modify: `summary.md`
- Optionally modify: `docs/GlomiAI.md` if implementation reveals a product wording mismatch

- [ ] **Step 1: Update local env shape**

In `.vscode/.env`, replace:

```env
CONSUMER_DEFAULT_LLM_PROVIDER_NAME=GPT
CONSUMER_DEFAULT_LLM_PROVIDER_TYPE=openai_compatible
CONSUMER_DEFAULT_LLM_DEFAULT_PROFILE=balanced
```

With:

```env
CONSUMER_DEFAULT_LLM_MODEL_NAME=qwen-plus
```

Keep:

```env
CONSUMER_DEFAULT_LLM_ENABLED=true
CONSUMER_DEFAULT_LLM_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
CONSUMER_DEFAULT_LLM_API_KEY=你的 DashScope API Key
```

- [ ] **Step 2: Update summary**

Append a dated entry to `summary.md` with:

```markdown
- 实现 E2 纠偏：移除 C 端模型档位/catalog/preference/selector，保留平台默认 OpenAI-compatible 主模型自动 seed。
- 配置收敛为 `CONSUMER_DEFAULT_LLM_API_BASE`、`CONSUMER_DEFAULT_LLM_API_KEY`、`CONSUMER_DEFAULT_LLM_MODEL_NAME`；provider type 固定为 `openai_compatible`，provider name 内部固定为 `Glomi Default`。
- 运行时回归 Onyx 原生默认模型链路：普通聊天、深度研究、标题生成、Craft 不再强制 consumer profile。
- 验证记录：补充实际 pytest、app startup、frontend typecheck 结果。
```

- [ ] **Step 3: Run complete focused verification**

Run:

```powershell
$env:PYTHONUTF8='1'; .venv\Scripts\python.exe -m pytest backend/tests/unit/onyx/db/test_consumer_llm.py backend/tests/unit/onyx/test_setup_consumer_llm.py backend/tests/unit/ee/onyx/server/tenants/test_provisioning.py backend/tests/unit/onyx/server/features/build/session/test_get_all_build_mode_llm_configs.py -q
```

Expected: all selected backend tests pass.

Then run:

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONPATH='backend'; .venv\Scripts\python.exe -c "from onyx.main import get_application; get_application(lifespan_override=lambda app: None); print('app-ok')"
```

Expected: prints `app-ok`.

Then run:

```powershell
cd web
npm run types:check
```

Expected: TypeScript passes.

- [ ] **Step 4: Final search for removed concepts**

Run:

```powershell
rg -n "CONSUMER_DEFAULT_LLM_DEFAULT_PROFILE|CONSUMER_DEFAULT_LLM_PROVIDER_TYPE|CONSUMER_DEFAULT_LLM_PROVIDER_NAME|model-catalog|model-preference|ConsumerModelProfileSelector|consumer_model_catalog|consumerModels" backend web .vscode
```

Expected: no matches except intentionally retained internal constants if `CONSUMER_DEFAULT_LLM_PROVIDER_NAME` / `CONSUMER_DEFAULT_LLM_PROVIDER_TYPE` remain as fixed Python constants.

- [ ] **Step 5: Commit docs/env verification**

Run:

```powershell
git add .vscode/.env summary.md docs/GlomiAI.md
git commit -m "docs: record platform default llm implementation"
```

- [ ] **Step 6: Report final status**

Collect:

```powershell
git status -sb
git log --oneline -n 6
```

Expected: branch is only dirty for unrelated pre-existing untracked `coding_agent_tool.py`, or clean if the user later decides to track it.

Report commits, verification results, and any skipped command with reason.

---

## Tests

- Unit: `backend/tests/unit/onyx/db/test_consumer_llm.py`
- Unit: `backend/tests/unit/onyx/test_setup_consumer_llm.py`
- Unit: `backend/tests/unit/ee/onyx/server/tenants/test_provisioning.py`
- Unit: `backend/tests/unit/onyx/server/features/build/session/test_get_all_build_mode_llm_configs.py`
- Startup auth contract: build `onyx.main.get_application()`
- Frontend typecheck: `npm run types:check`

## Plan Self-Review

- Spec coverage: seed config, one-model provider, idempotence, removal of APIs/UI, runtime default path, env/docs, and verification are covered by Tasks 1-4.
- Placeholder scan: no placeholder markers or vague “handle edge cases” steps remain.
- Type consistency: `ConsumerDefaultLLMConfig` fields match the proposed tests and implementation; env names match the spec; deleted frontend modules match current imports.
