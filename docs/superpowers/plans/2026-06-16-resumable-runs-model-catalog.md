# Resumable Runs and Model Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase A foundation for selectable Glomi models, backend-sourced model capabilities, image-upload gating, answer-shape policy hooks, and refresh-resumable chat runs.

**Architecture:** Reuse Onyx's existing `LLMProvider` / `ModelConfiguration` / `LLMModelFlow` model store as the model catalog persistence layer, and evolve the current single default consumer LLM seed into idempotent platform catalog sync. Add a lightweight `chat_run` / `chat_run_event` persistence layer around the existing streaming path so current chat answers can be resumed after refresh without building the full future task orchestrator.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, Alembic, Pydantic, pytest, Next.js 15, React 18, TypeScript, Zustand, SWR, Opal UI components.

---

## File Structure

Backend model catalog:

- Create `backend/onyx/db/glomi_model_catalog.py`: platform model definitions, provider request builder, and idempotent tenant sync.
- Modify `backend/onyx/db/consumer_llm.py`: delegate consumer LLM seed to the catalog sync while keeping the old single-model config as a credential fallback.
- Modify tenant setup call sites that already call `seed_consumer_default_llm_provider`; no new DB writes outside `backend/onyx/db`.
- Test `backend/tests/unit/onyx/db/test_glomi_model_catalog.py`.

Backend chat model API:

- Modify `backend/onyx/server/query_and_chat/models.py`: add response models for available chat models.
- Modify `backend/onyx/server/query_and_chat/chat_backend.py`: add `GET /api/chat/available-models`.
- Test `backend/tests/unit/onyx/server/query_and_chat/test_available_models_api.py`.

Frontend model selector and vision gating:

- Modify `web/src/lib/languageModels/types.ts`: keep existing model capability fields; no broad new type unless API response requires it.
- Modify `web/src/refresh-components/popovers/ModelSelector.tsx`: support single-model mode as first-class UI, not only multi-model add/remove.
- Modify `web/src/refresh-components/popovers/ModelListContent.tsx`: show Chinese capability labels and disabled state copy.
- Modify `web/src/hooks/useChatController.ts`: image upload gating uses backend model capabilities for the selected model, with GPT-5.5/Qwen3.7 Plus hint.
- Modify `web/src/refresh-pages/AppPage.tsx`: always render the model selector pill when models exist, even when multi-model is inactive.
- Test `web/src/refresh-components/popovers/ModelSelector.test.tsx` and `web/src/hooks/useChatController.test.tsx` or closest existing test harness.

Answer shape:

- Modify `backend/onyx/prompts/search_strategy.py`: promote direct/focused/deep answer-shape language if current wording is not explicit enough.
- Test `backend/tests/unit/onyx/prompts/test_search_strategy.py`.

Resumable runs:

- Create Alembic revision under `backend/alembic/versions/`.
- Modify `backend/onyx/db/models.py`: add `ChatRun` and `ChatRunEvent`.
- Create `backend/onyx/db/chat_run.py`: run creation, event append, replay, status update, active-run lookup.
- Modify `backend/onyx/server/query_and_chat/streaming_models.py` only if a new run metadata packet is required.
- Modify `backend/onyx/server/query_and_chat/models.py`: expose active run metadata on `ChatSessionDetailResponse`.
- Modify `backend/onyx/chat/process_message.py`: create a run, append packets, and mark completion/failure/cancel.
- Modify `backend/onyx/server/query_and_chat/chat_backend.py`: add resume endpoint.
- Modify `web/src/app/app/services/streamingModels.ts`: add run metadata packet type only if introduced.
- Modify `web/src/app/app/services/lib.tsx`: add `resumeChatRun()`.
- Modify `web/src/hooks/useChatSessionController` or the session loading path that owns chat-session hydration: reconnect when active run metadata is present.
- Test backend run replay and frontend refresh behavior.

Documentation:

- Modify `summary.md`.
- Modify `docs/GlomiAI.md` only if implementation decisions diverge from the approved design.

---

## Task 1: Backend Glomi Model Catalog

**Files:**
- Create: `backend/onyx/db/glomi_model_catalog.py`
- Modify: `backend/onyx/db/consumer_llm.py`
- Test: `backend/tests/unit/onyx/db/test_glomi_model_catalog.py`

- [ ] **Step 1: Write failing tests for the platform catalog definitions**

Add this test file:

```python
from onyx.db.glomi_model_catalog import GLOMI_PLATFORM_MODELS
from onyx.db.glomi_model_catalog import get_glomi_platform_model_catalog


def test_catalog_contains_phase_a_models() -> None:
    catalog = get_glomi_platform_model_catalog()
    model_names = {model.model_name for model in catalog.models}

    assert model_names == {
        "gpt-5.5",
        "qwen3.7-plus",
        "deepseek-v4-pro",
        "glm-5.2",
    }


def test_phase_a_model_capabilities_are_explicit() -> None:
    models = {model.model_name: model for model in GLOMI_PLATFORM_MODELS}

    assert models["gpt-5.5"].supports_image_input is True
    assert models["gpt-5.5"].supports_reasoning is True
    assert "vision" in models["gpt-5.5"].roles

    assert models["qwen3.7-plus"].supports_image_input is True
    assert models["qwen3.7-plus"].supports_reasoning is True
    assert "vision" in models["qwen3.7-plus"].roles

    assert models["deepseek-v4-pro"].supports_image_input is False
    assert models["deepseek-v4-pro"].supports_reasoning is True

    assert models["glm-5.2"].supports_image_input is False
    assert models["glm-5.2"].supports_reasoning is True
    assert "coding" in models["glm-5.2"].roles
```

- [ ] **Step 2: Run the failing catalog tests**

Run:

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest backend\tests\unit\onyx\db\test_glomi_model_catalog.py -xv
```

Expected: FAIL with `ModuleNotFoundError: No module named 'onyx.db.glomi_model_catalog'`.

- [ ] **Step 3: Add the platform catalog module**

Create `backend/onyx/db/glomi_model_catalog.py`:

```python
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_API_BASE
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_API_KEY
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_ENABLED
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

GlomiModelRole = Literal[
    "fast",
    "balanced",
    "reasoning",
    "research",
    "vision",
    "coding",
]


@dataclass(frozen=True)
class GlomiPlatformModel:
    model_name: str
    display_name: str
    supports_image_input: bool
    supports_reasoning: bool
    roles: tuple[GlomiModelRole, ...]
    is_default: bool = False


@dataclass(frozen=True)
class GlomiPlatformModelCatalog:
    provider_name: str
    provider_type: str
    api_base: str | None
    api_key: str | None
    enabled: bool
    models: tuple[GlomiPlatformModel, ...]


@dataclass(frozen=True)
class GlomiModelCatalogSyncResult:
    synced: bool
    reason: str
    model_count: int = 0


GLOMI_PLATFORM_MODELS: tuple[GlomiPlatformModel, ...] = (
    GlomiPlatformModel(
        model_name="gpt-5.5",
        display_name="GPT-5.5",
        supports_image_input=True,
        supports_reasoning=True,
        roles=("balanced", "reasoning", "research", "vision", "coding"),
        is_default=True,
    ),
    GlomiPlatformModel(
        model_name="qwen3.7-plus",
        display_name="Qwen3.7 Plus",
        supports_image_input=True,
        supports_reasoning=True,
        roles=("balanced", "reasoning", "research", "vision"),
    ),
    GlomiPlatformModel(
        model_name="deepseek-v4-pro",
        display_name="DeepSeek V4 Pro",
        supports_image_input=False,
        supports_reasoning=True,
        roles=("reasoning", "research"),
    ),
    GlomiPlatformModel(
        model_name="glm-5.2",
        display_name="GLM-5.2",
        supports_image_input=False,
        supports_reasoning=True,
        roles=("reasoning", "research", "coding"),
    ),
)


def get_glomi_platform_model_catalog() -> GlomiPlatformModelCatalog:
    return GlomiPlatformModelCatalog(
        provider_name=CONSUMER_DEFAULT_LLM_PROVIDER_NAME,
        provider_type=CONSUMER_DEFAULT_LLM_PROVIDER_TYPE,
        api_base=CONSUMER_DEFAULT_LLM_API_BASE,
        api_key=CONSUMER_DEFAULT_LLM_API_KEY,
        enabled=CONSUMER_DEFAULT_LLM_ENABLED,
        models=GLOMI_PLATFORM_MODELS,
    )


def _default_model_name(models: tuple[GlomiPlatformModel, ...]) -> str:
    for model in models:
        if model.is_default:
            return model.model_name
    return models[0].model_name


def _build_provider_request(
    catalog: GlomiPlatformModelCatalog,
) -> LLMProviderUpsertRequest:
    return LLMProviderUpsertRequest(
        name=catalog.provider_name,
        provider=catalog.provider_type,
        api_key=catalog.api_key,
        api_base=catalog.api_base,
        api_key_changed=True,
        is_public=True,
        is_auto_mode=False,
        model_configurations=[
            ModelConfigurationUpsertRequest(
                name=model.model_name,
                is_visible=True,
                max_input_tokens=None,
                supports_image_input=model.supports_image_input,
                supports_reasoning=model.supports_reasoning,
                display_name=model.display_name,
                custom_display_name=None,
            )
            for model in catalog.models
        ],
    )


def sync_glomi_platform_model_catalog(
    db_session: Session,
    catalog: GlomiPlatformModelCatalog | None = None,
) -> GlomiModelCatalogSyncResult:
    catalog = catalog or get_glomi_platform_model_catalog()
    if not catalog.enabled:
        return GlomiModelCatalogSyncResult(synced=False, reason="disabled")
    if not catalog.api_key:
        return GlomiModelCatalogSyncResult(synced=False, reason="missing_api_key")
    if not catalog.api_base:
        return GlomiModelCatalogSyncResult(synced=False, reason="missing_api_base")
    if not catalog.models:
        return GlomiModelCatalogSyncResult(synced=False, reason="missing_models")

    request = _build_provider_request(catalog)
    existing_provider = fetch_existing_llm_provider_by_name_and_type(
        name=catalog.provider_name,
        provider_type=catalog.provider_type,
        db_session=db_session,
    )
    if existing_provider:
        request.id = existing_provider.id
        request.api_key = existing_provider.api_key
        request.api_base = existing_provider.api_base
        request.api_version = existing_provider.api_version
        request.custom_config = existing_provider.custom_config
        request.api_key_changed = False

        catalog_model_names = {model.model_name for model in catalog.models}
        for existing_model_config in existing_provider.model_configurations:
            if existing_model_config.name in catalog_model_names:
                continue
            request.model_configurations.append(
                ModelConfigurationUpsertRequest.from_model(existing_model_config)
            )

    provider = upsert_llm_provider(request, db_session)
    current_default = fetch_default_llm_model(db_session)
    default_model_name = _default_model_name(catalog.models)
    if current_default is None:
        update_default_provider(provider.id, default_model_name, db_session)

    logger.info(
        "Synced Glomi platform model catalog with %d models",
        len(catalog.models),
    )
    return GlomiModelCatalogSyncResult(
        synced=True,
        reason="synced",
        model_count=len(catalog.models),
    )
```

- [ ] **Step 4: Update the consumer seed wrapper**

Replace the body of `seed_consumer_default_llm_provider()` in `backend/onyx/db/consumer_llm.py` with delegation to the new catalog sync, while preserving the public function name used by setup hooks:

```python
def seed_consumer_default_llm_provider(
    db_session: Session,
    config: ConsumerDefaultLLMConfig | None = None,
) -> ConsumerDefaultLLMSeedResult:
    from onyx.db.glomi_model_catalog import GlomiPlatformModelCatalog
    from onyx.db.glomi_model_catalog import sync_glomi_platform_model_catalog

    config = config or get_consumer_default_llm_config()
    catalog = GlomiPlatformModelCatalog(
        provider_name=CONSUMER_DEFAULT_LLM_PROVIDER_NAME,
        provider_type=CONSUMER_DEFAULT_LLM_PROVIDER_TYPE,
        api_base=config.api_base,
        api_key=config.api_key,
        enabled=config.enabled and config.auto_provision_enabled,
        models=(
            __import__(
                "onyx.db.glomi_model_catalog",
                fromlist=["GLOMI_PLATFORM_MODELS"],
            ).GLOMI_PLATFORM_MODELS
        ),
    )
    result = sync_glomi_platform_model_catalog(db_session, catalog)
    return ConsumerDefaultLLMSeedResult(
        seeded=result.synced,
        reason=result.reason,
    )
```

After this change, remove now-unused imports from `consumer_llm.py`. Keep the `ConsumerDefaultLLMConfig` dataclass because tests and setup code can still inject config.

- [ ] **Step 5: Run catalog tests**

Run:

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest backend\tests\unit\onyx\db\test_glomi_model_catalog.py -xv
```

Expected: PASS.

- [ ] **Step 6: Add sync behavior tests**

Extend `backend/tests/unit/onyx/db/test_glomi_model_catalog.py` with tests that use mocks around `upsert_llm_provider`, `fetch_existing_llm_provider_by_name_and_type`, `fetch_default_llm_model`, and `update_default_provider`:

```python
from unittest.mock import Mock

from onyx.db.glomi_model_catalog import GlomiPlatformModelCatalog
from onyx.db.glomi_model_catalog import sync_glomi_platform_model_catalog


def test_sync_skips_when_credentials_missing() -> None:
    catalog = GlomiPlatformModelCatalog(
        provider_name="Glomi Default",
        provider_type="openai_compatible",
        api_base="https://example.test/v1",
        api_key=None,
        enabled=True,
        models=GLOMI_PLATFORM_MODELS,
    )

    result = sync_glomi_platform_model_catalog(Mock(), catalog)

    assert result.synced is False
    assert result.reason == "missing_api_key"


def test_sync_builds_four_visible_model_configurations(mocker) -> None:
    db_session = Mock()
    provider = Mock()
    provider.id = 7
    mocker.patch(
        "onyx.db.glomi_model_catalog.fetch_existing_llm_provider_by_name_and_type",
        return_value=None,
    )
    upsert_mock = mocker.patch(
        "onyx.db.glomi_model_catalog.upsert_llm_provider",
        return_value=provider,
    )
    mocker.patch("onyx.db.glomi_model_catalog.fetch_default_llm_model", return_value=None)
    update_default_mock = mocker.patch(
        "onyx.db.glomi_model_catalog.update_default_provider"
    )
    catalog = GlomiPlatformModelCatalog(
        provider_name="Glomi Default",
        provider_type="openai_compatible",
        api_base="https://example.test/v1",
        api_key="test-key",
        enabled=True,
        models=GLOMI_PLATFORM_MODELS,
    )

    result = sync_glomi_platform_model_catalog(db_session, catalog)

    request = upsert_mock.call_args.args[0]
    assert result.synced is True
    assert [m.name for m in request.model_configurations] == [
        "gpt-5.5",
        "qwen3.7-plus",
        "deepseek-v4-pro",
        "glm-5.2",
    ]
    assert all(m.is_visible for m in request.model_configurations)
    assert request.model_configurations[0].supports_image_input is True
    assert request.model_configurations[2].supports_image_input is False
    update_default_mock.assert_called_once_with(7, "gpt-5.5", db_session)
```

- [ ] **Step 7: Run focused backend catalog tests**

Run:

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest backend\tests\unit\onyx\db\test_glomi_model_catalog.py -xv
```

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

Run:

```powershell
git add backend\onyx\db\glomi_model_catalog.py backend\onyx\db\consumer_llm.py backend\tests\unit\onyx\db\test_glomi_model_catalog.py
git commit -m "feat: add glomi platform model catalog"
```

---

## Task 2: Backend Available Models API

**Files:**
- Modify: `backend/onyx/server/query_and_chat/models.py`
- Modify: `backend/onyx/server/query_and_chat/chat_backend.py`
- Test: `backend/tests/unit/onyx/server/query_and_chat/test_available_models_api.py`

- [ ] **Step 1: Add response models**

Append these models to `backend/onyx/server/query_and_chat/models.py` near the chat session response models:

```python
class AvailableChatModel(BaseModel):
    provider_id: int
    provider_name: str | None
    provider_type: str
    provider_display_name: str
    model_configuration_id: int | None
    model_id: str
    display_name: str
    supports_image_input: bool
    supports_reasoning: bool
    roles: list[str] = []
    is_default: bool = False
    is_selected: bool = False


class AvailableChatModelsResponse(BaseModel):
    models: list[AvailableChatModel]
```

- [ ] **Step 2: Write API shape test**

Create `backend/tests/unit/onyx/server/query_and_chat/test_available_models_api.py`:

```python
from onyx.server.query_and_chat.models import AvailableChatModel
from onyx.server.query_and_chat.models import AvailableChatModelsResponse


def test_available_chat_model_response_serializes_capabilities() -> None:
    response = AvailableChatModelsResponse(
        models=[
            AvailableChatModel(
                provider_id=1,
                provider_name="Glomi Default",
                provider_type="openai_compatible",
                provider_display_name="Glomi",
                model_configuration_id=10,
                model_id="gpt-5.5",
                display_name="GPT-5.5",
                supports_image_input=True,
                supports_reasoning=True,
                roles=["balanced", "vision"],
                is_default=True,
                is_selected=True,
            )
        ]
    )

    dumped = response.model_dump()

    assert dumped["models"][0]["model_id"] == "gpt-5.5"
    assert dumped["models"][0]["supports_image_input"] is True
    assert dumped["models"][0]["roles"] == ["balanced", "vision"]
```

- [ ] **Step 3: Run response model test**

Run:

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest backend\tests\unit\onyx\server\query_and_chat\test_available_models_api.py -xv
```

Expected: PASS after Step 1.

- [ ] **Step 4: Add API helper and route**

In `backend/onyx/server/query_and_chat/chat_backend.py`, import the new models and `fetch_default_llm_model`. Add this helper above the route definitions:

```python
def _model_display_name(model_config: ModelConfigurationView) -> str:
    return (
        model_config.custom_display_name
        or model_config.display_name
        or model_config.name
    )


def _model_roles(model_name: str) -> list[str]:
    from onyx.db.glomi_model_catalog import GLOMI_PLATFORM_MODELS

    for model in GLOMI_PLATFORM_MODELS:
        if model.model_name == model_name:
            return list(model.roles)
    return []
```

Add this route near other `/chat` settings endpoints:

```python
@router.get("/available-models")
def get_available_chat_models(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> AvailableChatModelsResponse:
    default_model = fetch_default_llm_model(db_session)
    providers = fetch_existing_llm_providers(
        db_session=db_session,
        flow_type_filter=[LLMModelFlowType.CHAT],
        only_public=True,
    )

    models: list[AvailableChatModel] = []
    selected_model = user.default_model
    for provider in providers:
        provider_view = LLMProviderView.from_model(provider)
        for model_config in provider_view.model_configurations:
            if not model_config.is_visible:
                continue
            display_name = _model_display_name(model_config)
            structured_value = structure_model_choice(
                provider_name=provider.name or "",
                provider_type=provider.provider,
                model_name=model_config.name,
            )
            models.append(
                AvailableChatModel(
                    provider_id=provider.id,
                    provider_name=provider.name,
                    provider_type=provider.provider,
                    provider_display_name=provider_view.provider_display_name,
                    model_configuration_id=model_config.id,
                    model_id=model_config.name,
                    display_name=display_name,
                    supports_image_input=model_config.supports_image_input,
                    supports_reasoning=model_config.supports_reasoning,
                    roles=_model_roles(model_config.name),
                    is_default=(
                        default_model is not None
                        and default_model.id == model_config.id
                    ),
                    is_selected=selected_model == structured_value,
                )
            )

    return AvailableChatModelsResponse(models=models)
```

Required imports for the route:

```python
from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import fetch_default_llm_model
from onyx.db.llm import fetch_existing_llm_providers
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.llm.models import LLMProviderView
from onyx.server.manage.llm.models import ModelConfigurationView
```

- [ ] **Step 5: Run import/type focused backend checks**

Run:

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest backend\tests\unit\onyx\server\query_and_chat\test_available_models_api.py -xv
.venv\Scripts\python.exe -m ruff check backend\onyx\server\query_and_chat backend\tests\unit\onyx\server\query_and_chat\test_available_models_api.py
```

Expected: tests PASS and ruff PASS.

- [ ] **Step 6: Commit Task 2**

Run:

```powershell
git add backend\onyx\server\query_and_chat\models.py backend\onyx\server\query_and_chat\chat_backend.py backend\tests\unit\onyx\server\query_and_chat\test_available_models_api.py
git commit -m "feat: expose chat model capabilities"
```

---

## Task 3: Frontend Model Selector and Vision Gating

**Files:**
- Modify: `web/src/refresh-components/popovers/ModelSelector.tsx`
- Modify: `web/src/refresh-components/popovers/ModelListContent.tsx`
- Modify: `web/src/hooks/useChatController.ts`
- Modify: `web/src/refresh-pages/AppPage.tsx`
- Test: `web/src/refresh-components/popovers/ModelSelector.test.tsx`
- Test: `web/src/lib/clipboard.test.ts` may remain unchanged; paste detection already exists.

- [ ] **Step 1: Add selector test for capability labels**

Create `web/src/refresh-components/popovers/ModelSelector.test.tsx` with a minimal render around `ModelListContent`:

```typescript
import { render, screen } from "@testing-library/react";
import ModelListContent from "@/refresh-components/popovers/ModelListContent";

describe("ModelListContent", () => {
  it("renders capability labels from backend model configuration", () => {
    render(
      <ModelListContent
        llmProviders={[
          {
            id: 1,
            name: "Glomi Default",
            provider: "openai_compatible",
            provider_display_name: "Glomi",
            model_configurations: [
              {
                id: 1,
                name: "gpt-5.5",
                is_visible: true,
                max_input_tokens: null,
                supports_image_input: true,
                supports_reasoning: true,
                display_name: "GPT-5.5",
              },
            ],
          },
        ]}
        onSelect={() => undefined}
        isSelected={() => false}
      />
    );

    expect(screen.getByText("GPT-5.5")).toBeInTheDocument();
    expect(screen.getByText("图片, 深思")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run selector test and confirm failure**

Run:

```powershell
cd web
npm test -- ModelSelector.test.tsx
```

Expected: FAIL because current labels are `Vision, Reasoning`.

- [ ] **Step 3: Localize capability labels**

In `web/src/refresh-components/popovers/ModelListContent.tsx`, replace capability construction:

```typescript
const capabilities: string[] = [];
if (option.supportsImageInput) capabilities.push("图片");
if (option.supportsReasoning) capabilities.push("深思");
const description =
  capabilities.length > 0 ? capabilities.join(", ") : undefined;
```

Keep the rest of `renderModelItem` unchanged.

- [ ] **Step 4: Run selector test**

Run:

```powershell
cd web
npm test -- ModelSelector.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Update image upload error copy**

In `web/src/hooks/useChatController.ts`, replace the image unsupported toast in `handleMessageSpecificFileUpload`:

```typescript
if (imageFiles.length > 0 && !llmAcceptsImages) {
  toast.error("当前模型暂不支持图片。请切换到 GPT-5.5 或 Qwen3.7 Plus。");
  return;
}
```

- [ ] **Step 6: Always render the single-model selector pill**

In `web/src/refresh-pages/AppPage.tsx`, keep the existing `multiModel.selectedModels` state as the source for the pill. Ensure `AppInputBar` receives `selectedModels={multiModel.selectedModels}` and selector callbacks regardless of `multiModel.isMultiModelActive`. If `AppInputBar` already receives these props, do not add a second selector.

In `web/src/sections/input/AppInputBar.tsx`, import and render `ModelSelector` near the submit controls:

```typescript
import ModelSelector from "@/refresh-components/popovers/ModelSelector";
```

Add props if they are not already present:

```typescript
selectedModels: SelectedModel[];
onAddModel: (model: SelectedModel) => void;
onRemoveModel: (index: number) => void;
onReplaceModel: (index: number, model: SelectedModel) => void;
```

Render:

```tsx
<ModelSelector
  llmManager={llmManager}
  selectedModels={selectedModels}
  onAdd={onAddModel}
  onRemove={onRemoveModel}
  onReplace={onReplaceModel}
/>
```

Use the existing import path for `SelectedModel`:

```typescript
import ModelSelector, {
  SelectedModel,
} from "@/refresh-components/popovers/ModelSelector";
```

- [ ] **Step 7: Run frontend checks**

Run:

```powershell
cd web
npm test -- ModelSelector.test.tsx
npm run types:check
```

Expected: focused test PASS and typecheck PASS.

- [ ] **Step 8: Commit Task 3**

Run:

```powershell
git add web\src\refresh-components\popovers\ModelSelector.tsx web\src\refresh-components\popovers\ModelListContent.tsx web\src\hooks\useChatController.ts web\src\refresh-pages\AppPage.tsx web\src\sections\input\AppInputBar.tsx web\src\refresh-components\popovers\ModelSelector.test.tsx
git commit -m "feat: show selectable chat models"
```

---

## Task 4: Answer Shape Policy Lock-In

**Files:**
- Modify: `backend/onyx/prompts/search_strategy.py`
- Modify: `backend/tests/unit/onyx/prompts/test_search_strategy.py`

- [ ] **Step 1: Add failing test for named answer shapes**

Add to `backend/tests/unit/onyx/prompts/test_search_strategy.py`:

```python
from onyx.prompts.search_strategy import CHAT_RESEARCH_ANSWER_GUIDANCE


def test_chat_research_guidance_names_answer_shapes() -> None:
    guidance = CHAT_RESEARCH_ANSWER_GUIDANCE

    assert "direct_answer" in guidance
    assert "focused_brief" in guidance
    assert "deep_report" in guidance
    assert "Search depth does not imply answer length" in guidance
```

- [ ] **Step 2: Run focused prompt test**

Run:

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest backend\tests\unit\onyx\prompts\test_search_strategy.py -xv
```

Expected: FAIL if the current guidance has the policy but not the explicit shape names.

- [ ] **Step 3: Update guidance text**

In `backend/onyx/prompts/search_strategy.py`, extend `CHAT_RESEARCH_ANSWER_GUIDANCE` with this exact language:

```python
Answer shape policy for ordinary chat:
- Use `direct_answer` for simple facts, definitions, direct operations, and short troubleshooting.
- Use `focused_brief` by default for ordinary research, comparison, selection, and planning questions. Start with the useful judgment, then provide 3-5 key reasons, evidence strength, conflicts, and next steps when helpful.
- Use `deep_report` only when the user explicitly asks for a report, complete analysis, detailed plan, long-form document, or when the Deep Research workflow is active.
- Search depth does not imply answer length. A deep or medium search can still produce a concise focused_brief.
```

- [ ] **Step 4: Run prompt tests**

Run:

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest backend\tests\unit\onyx\prompts -xv
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

Run:

```powershell
git add backend\onyx\prompts\search_strategy.py backend\tests\unit\onyx\prompts\test_search_strategy.py
git commit -m "docs: lock chat answer shape policy"
```

---

## Task 5: Resumable Run Schema and DB Layer

**Files:**
- Modify: `backend/onyx/db/models.py`
- Create: `backend/onyx/db/chat_run.py`
- Create: one new Alembic file under `backend/alembic/versions/` whose filename ends with `_add_chat_run_events.py`; the exact revision prefix is generated by Alembic in Step 1.
- Test: `backend/tests/unit/onyx/db/test_chat_run.py`

- [ ] **Step 1: Generate Alembic revision**

Run:

```powershell
.venv\Scripts\alembic.exe revision -m "add chat run events"
```

Expected: a new file under `backend/alembic/versions/`.

- [ ] **Step 2: Edit migration**

In the generated migration file, create:

```python
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def upgrade() -> None:
    op.create_table(
        "chat_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "chat_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assistant_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_message.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("model_provider", sa.String(), nullable=True),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_chat_run_chat_session_status", "chat_run", ["chat_session_id", "status"])
    op.create_index("ix_chat_run_assistant_message", "chat_run", ["assistant_message_id"])

    op.create_table(
        "chat_run_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("packet_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "seq", name="uq_chat_run_event_run_seq"),
    )
    op.create_index("ix_chat_run_event_run_seq", "chat_run_event", ["run_id", "seq"])


def downgrade() -> None:
    op.drop_index("ix_chat_run_event_run_seq", table_name="chat_run_event")
    op.drop_table("chat_run_event")
    op.drop_index("ix_chat_run_assistant_message", table_name="chat_run")
    op.drop_index("ix_chat_run_chat_session_status", table_name="chat_run")
    op.drop_table("chat_run")
```

- [ ] **Step 3: Add ORM models**

Add to `backend/onyx/db/models.py` near `ChatMessage`:

```python
class ChatRun(Base):
    __tablename__ = "chat_run"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    chat_session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("chat_session.id", ondelete="CASCADE")
    )
    user_message_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chat_message.id", ondelete="CASCADE")
    )
    assistant_message_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chat_message.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    model_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatRunEvent(Base):
    __tablename__ = "chat_run_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("chat_run.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    packet_json: Mapped[dict] = mapped_column(postgresql.JSONB(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

Use existing imports for `UUID`, `datetime`, `func`, `DateTime`, `Text`, and `postgresql`; add missing imports at the top of the file.

- [ ] **Step 4: Add DB helper tests**

Create `backend/tests/unit/onyx/db/test_chat_run.py`:

```python
from uuid import uuid4

from onyx.db.chat_run import next_event_seq


def test_next_event_seq_starts_at_zero() -> None:
    assert next_event_seq([]) == 0


def test_next_event_seq_increments_after_existing_events() -> None:
    class Event:
        def __init__(self, seq: int) -> None:
            self.seq = seq

    assert next_event_seq([Event(0), Event(1), Event(2)]) == 3
```

- [ ] **Step 5: Create DB helper module**

Create `backend/onyx/db/chat_run.py`:

```python
from datetime import datetime
from datetime import timezone
from uuid import UUID
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import ChatRun
from onyx.db.models import ChatRunEvent

RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"


def next_event_seq(events: list[object]) -> int:
    if not events:
        return 0
    return max(int(getattr(event, "seq")) for event in events) + 1


def create_chat_run__no_commit(
    db_session: Session,
    chat_session_id: UUID,
    user_message_id: int,
    assistant_message_id: int,
    model_provider: str | None,
    model_name: str | None,
) -> ChatRun:
    run = ChatRun(
        id=uuid4(),
        chat_session_id=chat_session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        status=RUNNING,
        model_provider=model_provider,
        model_name=model_name,
    )
    db_session.add(run)
    db_session.flush()
    return run


def append_chat_run_event__no_commit(
    db_session: Session,
    run_id: UUID,
    packet_json: dict,
) -> ChatRunEvent:
    existing_events = list(
        db_session.scalars(
            select(ChatRunEvent).where(ChatRunEvent.run_id == run_id)
        ).all()
    )
    event = ChatRunEvent(
        run_id=run_id,
        seq=next_event_seq(existing_events),
        packet_json=packet_json,
    )
    db_session.add(event)
    db_session.flush()
    return event


def mark_chat_run_status__no_commit(
    db_session: Session,
    run_id: UUID,
    status: str,
    error_detail: str | None = None,
) -> None:
    run = db_session.get(ChatRun, run_id)
    if run is None:
        return
    run.status = status
    run.error_detail = error_detail
    run.updated_at = datetime.now(timezone.utc)
    if status in {COMPLETED, FAILED, CANCELLED}:
        run.completed_at = datetime.now(timezone.utc)


def fetch_active_chat_run(
    db_session: Session,
    chat_session_id: UUID,
) -> ChatRun | None:
    return db_session.scalar(
        select(ChatRun)
        .where(ChatRun.chat_session_id == chat_session_id)
        .where(ChatRun.status == RUNNING)
        .order_by(ChatRun.created_at.desc())
    )


def fetch_chat_run_events_after(
    db_session: Session,
    run_id: UUID,
    after_seq: int | None,
) -> list[ChatRunEvent]:
    stmt = select(ChatRunEvent).where(ChatRunEvent.run_id == run_id)
    if after_seq is not None:
        stmt = stmt.where(ChatRunEvent.seq > after_seq)
    return list(db_session.scalars(stmt.order_by(ChatRunEvent.seq.asc())).all())
```

- [ ] **Step 6: Run DB helper tests and migration check**

Run:

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest backend\tests\unit\onyx\db\test_chat_run.py -xv
.venv\Scripts\python.exe -m ruff check backend\onyx\db\chat_run.py backend\tests\unit\onyx\db\test_chat_run.py
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

Run:

```powershell
git add backend\onyx\db\models.py backend\onyx\db\chat_run.py backend\alembic\versions backend\tests\unit\onyx\db\test_chat_run.py
git commit -m "feat: add chat run event storage"
```

---

## Task 6: Stream Event Persistence and Resume API

**Files:**
- Modify: `backend/onyx/chat/process_message.py`
- Modify: `backend/onyx/server/query_and_chat/models.py`
- Modify: `backend/onyx/server/query_and_chat/chat_backend.py`
- Test: `backend/tests/unit/onyx/chat/test_resumable_chat_run.py`

- [ ] **Step 1: Add active run response model fields**

Add to `backend/onyx/server/query_and_chat/models.py`:

```python
class ActiveChatRun(BaseModel):
    run_id: UUID
    assistant_message_id: int
    status: str
    latest_seq: int | None = None


class ResumeChatRunRequest(BaseModel):
    run_id: UUID
    after_seq: int | None = None
```

Add to `ChatSessionDetailResponse`:

```python
active_run: ActiveChatRun | None = None
```

- [ ] **Step 2: Attach active run metadata during session load**

In `get_chat_session()` in `backend/onyx/server/query_and_chat/chat_backend.py`, after the processing check:

```python
active_run_response: ActiveChatRun | None = None
active_run = fetch_active_chat_run(db_session, session_id)
if active_run is not None:
    active_events = fetch_chat_run_events_after(db_session, active_run.id, None)
    latest_seq = active_events[-1].seq if active_events else None
    active_run_response = ActiveChatRun(
        run_id=active_run.id,
        assistant_message_id=active_run.assistant_message_id,
        status=active_run.status,
        latest_seq=latest_seq,
    )
```

Pass `active_run=active_run_response` into `ChatSessionDetailResponse`.

- [ ] **Step 3: Add resume endpoint**

In `chat_backend.py`, add:

```python
@router.post("/resume-chat-run")
def resume_chat_run(
    resume_req: ResumeChatRunRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> StreamingResponse:
    run = db_session.get(ChatRun, resume_req.run_id)
    if run is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Chat run not found")

    get_chat_session_by_id(
        chat_session_id=run.chat_session_id,
        user_id=user.id,
        db_session=db_session,
    )

    def event_generator() -> Generator[str, None, None]:
        for event in fetch_chat_run_events_after(
            db_session,
            resume_req.run_id,
            resume_req.after_seq,
        ):
            yield get_json_line(event.packet_json)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

Phase A replay returns stored events. Live tailing can be added in Task 7 frontend by reconnecting again if run remains active, or expanded in a follow-up with Redis pub/sub. Keep the endpoint permission-safe.

- [ ] **Step 4: Persist packets in stream generator**

In `backend/onyx/chat/process_message.py`, create a run after reserved assistant messages exist. In `_run_models`, wrap packet emission:

```python
def _persist_packet_for_run(packet: Packet) -> None:
    with get_session_with_current_tenant() as db_session:
        append_chat_run_event__no_commit(
            db_session=db_session,
            run_id=run_id,
            packet_json=packet.model_dump(mode="json"),
        )
        db_session.commit()
```

Call `_persist_packet_for_run(packet)` immediately before yielding each `Packet` from the drain loop. Mark the run `COMPLETED`, `FAILED`, or `CANCELLED` in the same completion paths that currently call `set_processing_status(..., False)`.

- [ ] **Step 5: Run backend resume tests**

Add focused tests for permission-free helper behavior first, then run:

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest backend\tests\unit\onyx\chat\test_resumable_chat_run.py backend\tests\unit\onyx\db\test_chat_run.py -xv
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

Run:

```powershell
git add backend\onyx\chat\process_message.py backend\onyx\server\query_and_chat\models.py backend\onyx\server\query_and_chat\chat_backend.py backend\tests\unit\onyx\chat\test_resumable_chat_run.py
git commit -m "feat: persist and replay chat run events"
```

---

## Task 7: Frontend Resume Hook

**Files:**
- Modify: `web/src/app/app/interfaces.ts`
- Modify: `web/src/app/app/services/lib.tsx`
- Modify: session loading hook that receives `BackendChatSession`
- Test: focused frontend hook test if an existing harness exists

- [ ] **Step 1: Add active run interface**

In `web/src/app/app/interfaces.ts`, add:

```typescript
export interface ActiveChatRun {
  run_id: string;
  assistant_message_id: number;
  status: string;
  latest_seq: number | null;
}
```

Add to `BackendChatSession`:

```typescript
active_run?: ActiveChatRun | null;
```

- [ ] **Step 2: Add resume service**

In `web/src/app/app/services/lib.tsx`, add:

```typescript
export async function* resumeChatRun({
  runId,
  afterSeq,
  signal,
}: {
  runId: string;
  afterSeq?: number | null;
  signal: AbortSignal;
}): AsyncGenerator<PacketType, void, unknown> {
  const response = await fetch("/api/chat/resume-chat-run", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      run_id: runId,
      after_seq: afterSeq ?? null,
    }),
    signal,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail ?? `HTTP error! status: ${response.status}`);
  }

  yield* handleSSEStream<PacketType>(response, signal);
}
```

- [ ] **Step 3: Reconnect on session hydration**

In the hook that processes `BackendChatSession` into the message tree, detect:

```typescript
if (backendSession.active_run?.status === "running") {
  updateChatState(sessionId, "streaming");
  // Start resumeChatRun and pass incoming packets through the same packet handler
  // used by sendMessage streaming.
}
```

Reuse the existing streaming packet handler from `useChatController` rather than adding a separate parser. If that parser is not reusable, extract it into `web/src/app/app/services/chatPacketHandler.ts` with a pure function that accepts `PacketType` and returns message-tree updates.

- [ ] **Step 4: Run frontend typecheck**

Run:

```powershell
cd web
npm run types:check
```

Expected: PASS.

- [ ] **Step 5: Commit Task 7**

Run:

```powershell
git add web\src\app\app\interfaces.ts web\src\app\app\services\lib.tsx web\src\hooks web\src\app\app\services
git commit -m "feat: resume active chat runs on load"
```

---

## Task 8: End-to-End Verification and Documentation

**Files:**
- Modify: `summary.md`
- Modify: `docs/GlomiAI.md` only if implementation changed the plan

- [ ] **Step 1: Run backend focused test suite**

Run:

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m pytest backend\tests\unit\onyx\db\test_glomi_model_catalog.py backend\tests\unit\onyx\db\test_chat_run.py backend\tests\unit\onyx\prompts backend\tests\unit\onyx\server\query_and_chat -xv
```

Expected: PASS.

- [ ] **Step 2: Run backend ruff**

Run:

```powershell
.venv\Scripts\python.exe -m ruff check backend\onyx\db\glomi_model_catalog.py backend\onyx\db\chat_run.py backend\onyx\db\consumer_llm.py backend\onyx\server\query_and_chat backend\onyx\chat\process_message.py backend\tests\unit\onyx\db backend\tests\unit\onyx\server\query_and_chat
```

Expected: PASS.

- [ ] **Step 3: Run frontend checks**

Run:

```powershell
cd web
npm test -- ModelSelector.test.tsx
npm run types:check
```

Expected: PASS.

- [ ] **Step 4: Manual local verification**

Use the running app at `http://localhost:3000`:

1. Log in with `a@example.com` / `a`.
2. Confirm the input bar model pill shows GPT-5.5 or the current default.
3. Open the selector and confirm GPT-5.5, Qwen3.7 Plus, DeepSeek V4 Pro, and GLM-5.2 are visible.
4. Confirm GPT-5.5 and Qwen3.7 Plus show image capability.
5. Select DeepSeek V4 Pro and paste an image; confirm the app blocks upload with the Chinese hint.
6. Select GPT-5.5 and paste an image; confirm the image becomes an attachment.
7. Start a slow answer, refresh, and confirm the in-progress state resumes or replays stored progress.

- [ ] **Step 5: Update summary**

Append to `summary.md`:

```markdown
## 2026-06-16

- Implemented Phase A platform model catalog sync: GPT-5.5, Qwen3.7 Plus, DeepSeek V4 Pro, and GLM-5.2 are seeded as visible model configurations under the platform provider, with backend-owned image/reasoning capabilities.
- Exposed backend model capabilities to the chat UI and rendered a model selector pill near the input controls.
- Updated image upload gating to trust backend `supports_image_input`; GPT-5.5/Qwen3.7 Plus allow pasted images, DeepSeek V4 Pro/GLM-5.2 show a model capability hint.
- Added lightweight chat run/event persistence and resume plumbing so refreshes can recover in-progress stream packets.
- Verification: record the exact commands run in Task 8 Steps 1-4 and their PASS/FAIL results in this bullet before committing `summary.md`.
```

Replace the final verification bullet with the exact commands and pass/fail results from this task.

- [ ] **Step 6: Commit Task 8**

Run:

```powershell
git add summary.md docs\GlomiAI.md
git commit -m "docs: record model catalog implementation"
```

---

## Self-Review

Spec coverage:

- Refresh recovery: Tasks 5-7 add run/event storage, resume API, and frontend reconnect.
- Model roles/provider capability profiles: Tasks 1-2 add backend catalog and capability API.
- Answer length policy: Task 4 locks named answer shapes in prompt tests.
- Image/document input: Task 3 makes image gating depend on backend model capability and improves user copy. Full OCR/document fallback is not in this Phase A plan because the approved later direction was frontend allow/deny based on selected model support.
- Existing-account model sync: Task 1 evolves the existing tenant seed hook, preserving old call sites and making sync idempotent.
- Frontend selector: Task 3 uses existing `ModelSelector`/`ModelListContent` instead of building a second UI.

Type consistency:

- Backend model id is called `model_id` in the new API and `modelName` in existing frontend `SelectedModel`.
- Existing frontend `supports_image_input` maps to `supportsImageInput` through the current LLM option builder.
- Run ids are UUIDs in Python and strings in TypeScript.

Implementation order:

- Execute Tasks 1-4 first to deliver model selector and image gating.
- Execute Tasks 5-7 as the second slice because resumable runs touch DB schema and the streaming core.
