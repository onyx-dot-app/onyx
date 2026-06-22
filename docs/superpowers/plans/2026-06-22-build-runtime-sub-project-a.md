# build_runtime 子项目 A 实现计划(Daytona + Pi 落地页端到端)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 `build_runtime` 地基(领域模型 + Provider/Adapter 接口 + 编排状态机 + 1 个落地页模板),把「自然语言需求 → Daytona 沙箱 → Pi 构建 Next.js 落地页 → 预览 URL → 事件回流」端到端打通,与现有 opencode Craft 并行、feature flag 控制。

**Architecture:** Python 侧只做编排与中继。`BuildOrchestrator` 驱动一个状态机:`SandboxProvider`(Daytona)起沙箱并暴露预览,`BuilderAdapter`(Pi)在沙箱内构建。沙箱内一个**我们自己的 launcher 脚本**把 Pi 的原始输出归一化成我们定义的 `BuilderEvent` JSONL 契约,Adapter 只依赖这个契约,不依赖 Pi 内部 schema。事件持久化进 `build_runtime_event` 表(仿现有 `chat_run_event`:seq + JSONB),SSE 端点按 seq 轮询回放。

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy / Alembic / Celery / Pydantic v2;`daytona` Python SDK;Pi(`@earendil-works/pi-coding-agent`,沙箱内 Node);Next.js + Tailwind/shadcn(模板,在沙箱内)。

## Global Constraints

- **DB 操作只放** `backend/onyx/db/`;SQLAlchemy 表进 `backend/onyx/db/models.py`,枚举进 `backend/onyx/db/enums.py`。不沿用 `server/features/build/db/` 的旧偏差。
- **错误处理**用 `OnyxError(OnyxErrorCode.X, detail)`,**禁止** `HTTPException`。新错误码加到 `backend/onyx/error_handling/error_codes.py`。
- **FastAPI 路由禁止** `response_model`,直接给函数标返回类型。
- **每个 LLM 调用**必须开 generation span 并用 `LLMFlow` 标签(本计划新增 `LLMFlow.BUILD_SPEC_GENERATION`)。
- **Celery 任务**用 `@shared_task`,放 `backend/onyx/background/celery/tasks/`,enqueue 必带 `expires=`,超时在任务内实现。
- **前端**遵守 `web/AGENTS.md`:Opal 优先、`@/` 绝对导入、`function` 语法、自定义 Tailwind 颜色变量(`bg-background-neutral-01` 等,禁止 `bg-gray-100`)。
- **测试模型**:OpenAI 用 `gpt-5-mini`;真实外部依赖测试用 `python -m dotenv -f .vscode/.env run -- pytest ...`。
- **feature flag** `ENABLE_BUILD_RUNTIME` 关闭时,新模块零副作用,现有 opencode Craft 行为不变。
- **激活虚拟环境**:每次跑测试前 `source .venv/bin/activate`(不存在则先 `uv sync --frozen`)。
- 所有 Pydantic↔JSONB 列用 `backend/onyx/db/pydantic_type.py` 的 `PydanticType`,或手工存 `json.loads(model.model_dump_json())`。

---

## 文件结构(本子项目新建/修改)

```
backend/onyx/build_runtime/
  __init__.py
  configs.py                         # 新建:feature flag + Daytona endpoint + 默认模板
  schemas/
    __init__.py
    build_spec.py                    # 新建:BuildSpec / BuildSpecInputs / BuildSpecOutputs
    output_manifest.py               # 新建:OutputManifest / OutputFile / PreviewEntry
    build_session.py                 # 新建:BuildError + 领域视图模型
    events.py                        # 新建:BuilderEvent 契约(我们自己的事件)
    sandbox.py                       # 新建:CreateSandboxInput / PreviewInfo 等
    builder.py                       # 新建:StartBuildInput / BuilderConfig 等
  interfaces/
    __init__.py
    sandbox_provider.py              # 新建:SandboxProvider Protocol
    builder_adapter.py               # 新建:BuilderAdapter Protocol
  testing/
    __init__.py
    fakes.py                         # 新建:FakeSandboxProvider / FakeBuilderAdapter
  services/
    __init__.py
    template_service.py              # 新建:TemplateService / TemplateDescriptor
    spec_builder.py                  # 新建:SpecBuilder(NL→BuildSpec)
    build_orchestrator.py            # 新建:BuildOrchestrator 状态机(核心)
  providers/
    __init__.py
    sandbox/daytona_provider.py      # 新建:DaytonaSandboxProvider
    builder/pi_builder_adapter.py    # 新建:PiBuilderAdapter
  templates/landing_page/
    AGENTS.md                        # 新建
    SYSTEM.md                        # 新建
    output_contract.md               # 新建
  sandbox_image/
    Dockerfile                       # 新建:glomi-landing-page snapshot 镜像
    run_build.py                     # 新建:沙箱内 launcher(归一化 Pi → BuilderEvent JSONL)
    write_models_json.py             # 新建:从 env 写 ~/.pi/agent/models.json
backend/onyx/db/
  enums.py                           # 修改:加 BuildRuntimeStatus / BuildArtifactType 等
  models.py                          # 修改:加 BuildRuntimeSession / BuildRuntimeEvent 表
  build_runtime.py                   # 新建:DB 操作
backend/onyx/error_handling/error_codes.py   # 修改:加 BUILD_* 错误码
backend/onyx/tracing/flows.py        # 修改:加 LLMFlow.BUILD_SPEC_GENERATION
backend/onyx/background/celery/tasks/build_runtime/
  __init__.py                        # 新建
  tasks.py                           # 新建:run_build_session_task
backend/onyx/server/features/build_runtime/
  __init__.py
  api.py                             # 新建:路由(create/get/instruction/terminate/events SSE)
  sse.py                             # 新建:事件→SSE 帧
backend/onyx/main.py                 # 修改:include_router
backend/alembic/versions/<rev>_add_build_runtime_tables.py   # 新建迁移
web/src/app/build-runtime-dev/page.tsx       # 新建:最小内测触发页
web/src/hooks/useBuildRuntimeSession.ts      # 新建:SWR hook
backend/tests/unit/build_runtime/            # 新建:单元测试
backend/tests/external_dependency_unit/build_runtime/   # 新建:PG/真实依赖测试
```

---

## Task 1: 模块骨架 + feature flag + 依赖固定 + Daytona 连通 spike

**Files:**
- Create: `backend/onyx/build_runtime/__init__.py`(空)
- Create: `backend/onyx/build_runtime/configs.py`
- Modify: `backend/pyproject.toml`(加 `daytona` 依赖)
- Create: `docs/superpowers/plans/A-spike-notes.md`

**Interfaces:**
- Produces: `ENABLE_BUILD_RUNTIME: bool`、`DAYTONA_API_URL: str | None`、`DAYTONA_API_KEY: str | None`、`BUILD_RUNTIME_DEFAULT_SNAPSHOT: str`、`LANDING_PAGE_TEMPLATE_ID: str = "landing_page"`,均从 `configs.py` 导出。

- [ ] **Step 1: 写 configs**

```python
# backend/onyx/build_runtime/configs.py
"""Configuration for the build_runtime feature (Daytona + Pi delivery runtime).

Strangler module — parallel to server/features/build (opencode Craft). Gated by
ENABLE_BUILD_RUNTIME; when off, nothing here should run.
"""
import os

ENABLE_BUILD_RUNTIME = os.environ.get("ENABLE_BUILD_RUNTIME", "").lower() == "true"

# Self-hosted Daytona control-plane endpoint + key. For local dev this points at
# the docker-compose stack; in prod at the in-cluster Daytona API.
DAYTONA_API_URL = os.environ.get("DAYTONA_API_URL") or None
DAYTONA_API_KEY = os.environ.get("DAYTONA_API_KEY") or None

# Snapshot (OCI image) that the landing-page template builds in.
BUILD_RUNTIME_DEFAULT_SNAPSHOT = os.environ.get(
    "BUILD_RUNTIME_DEFAULT_SNAPSHOT", "glomi-landing-page"
)
LANDING_PAGE_TEMPLATE_ID = "landing_page"

# Port the in-sandbox Next.js dev server listens on; exposed via Daytona preview.
SANDBOX_PREVIEW_PORT = int(os.environ.get("BUILD_RUNTIME_PREVIEW_PORT", "3000"))
```

- [ ] **Step 2: 固定 daytona 依赖**

在 `backend/pyproject.toml` 的依赖区加一行(版本以 `uv add daytona` 实际解析为准):

```toml
    "daytona>=0.20.0",
```

运行:`cd backend && uv add daytona` (它会写入 pyproject + lock)。

- [ ] **Step 3: 本地 Daytona spike(手动验证,记录事实)**

按 Daytona OSS docker-compose 起本地全栈(参考 `https://www.daytona.io/docs/en/oss-deployment/`),拿到 `DAYTONA_API_URL` + `DAYTONA_API_KEY`,跑下面这段一次性脚本,确认 SDK 调用形态:

```python
# 临时脚本,验证后删除;结论记进 A-spike-notes.md
from daytona import Daytona, DaytonaConfig, CreateSandboxFromSnapshotParams
d = Daytona(DaytonaConfig(api_key="...", api_url="http://localhost:..."))
sb = d.create(CreateSandboxFromSnapshotParams(snapshot="daytona", language="python"))
sb.fs.upload_file(b"hello", "/workspace/hello.txt")
print(sb.process.exec("cat /workspace/hello.txt").result)
sb.public = True
print(sb.get_preview_link(3000).url)
d.delete(sb)
```

- [ ] **Step 4: 记录 spike 结论**

把实测到的:SDK 方法签名、`create`/`exec`/`upload_file`/`get_preview_link`/`delete`/`stop` 的真实返回字段、preview URL 形态、本地 endpoint,写进 `docs/superpowers/plans/A-spike-notes.md`。若与本计划后续任务里的 SDK 调用有出入,以 spike 实测为准并回头改对应任务。

- [ ] **Step 5: Commit**

```bash
git add backend/onyx/build_runtime/ backend/pyproject.toml backend/uv.lock docs/superpowers/plans/A-spike-notes.md
git commit -m "feat(build_runtime): module skeleton, configs, daytona dep, daytona spike notes"
```

---

## Task 2: 领域 Pydantic 模型 + BuilderEvent 契约

**Files:**
- Create: `backend/onyx/build_runtime/schemas/__init__.py`, `build_spec.py`, `output_manifest.py`, `build_session.py`, `events.py`, `sandbox.py`, `builder.py`
- Test: `backend/tests/unit/build_runtime/test_schemas.py`

**Interfaces:**
- Produces:
  - `BuildSpec`(字段:`title:str`,`goal:str`,`target_audience:str|None`,`requirements:list[str]`,`constraints:list[str]`,`visual_style:list[str]`,`inputs:BuildSpecInputs`,`outputs:BuildSpecOutputs`,`acceptance_criteria:list[str]`)
  - `OutputManifest`(`primary_artifact_path:str`,`primary_artifact_type:str`,`preview_entry:PreviewEntry|None`,`files:list[OutputFile]`,`notes:list[str]`)
  - `BuilderEvent`(Union,见下),每个成员有 `type:Literal[...]` + `at:str`
  - `BuildError`(`code:str`,`message:str`,`retryable:bool`,`details:dict`,`occurred_at:str`)
  - `CreateSandboxInput`,`CreateSandboxResult`,`PreviewInfo`,`SandboxFile`,`SandboxStatusInfo`,`CommandResult`
  - `StartBuildInput`,`StartBuildResult`,`BuilderConfig`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/build_runtime/test_schemas.py
from onyx.build_runtime.schemas.build_spec import BuildSpec
from onyx.build_runtime.schemas.events import (
    BuilderStarted, PreviewReady, BuilderFinished, parse_builder_event,
)
from onyx.build_runtime.schemas.output_manifest import OutputManifest


def test_build_spec_minimal_roundtrip():
    spec = BuildSpec(title="发布页", goal="生成中文产品落地页")
    dumped = spec.model_dump_json()
    again = BuildSpec.model_validate_json(dumped)
    assert again.title == "发布页"
    assert again.requirements == []  # default factory


def test_builder_event_discriminated_parse():
    raw = {"type": "preview_ready", "at": "2026-06-22T00:00:00Z", "port": 3000}
    ev = parse_builder_event(raw)
    assert isinstance(ev, PreviewReady)
    assert ev.port == 3000


def test_output_manifest_roundtrip():
    m = OutputManifest(primary_artifact_path="/workspace/out", primary_artifact_type="landing_page")
    assert OutputManifest.model_validate_json(m.model_dump_json()).primary_artifact_type == "landing_page"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `source .venv/bin/activate && pytest backend/tests/unit/build_runtime/test_schemas.py -v`
Expected: FAIL(`ModuleNotFoundError: onyx.build_runtime.schemas.build_spec`)

- [ ] **Step 3: 写 schemas**

```python
# backend/onyx/build_runtime/schemas/build_spec.py
from pydantic import BaseModel, Field


class BuildSpecInputs(BaseModel):
    uploaded_files: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    external_urls: list[str] = Field(default_factory=list)


class BuildSpecOutputs(BaseModel):
    primary_format: str = "web"
    extra_formats: list[str] = Field(default_factory=list)


class BuildSpec(BaseModel):
    title: str
    goal: str
    target_audience: str | None = None
    requirements: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    visual_style: list[str] = Field(default_factory=list)
    inputs: BuildSpecInputs = Field(default_factory=BuildSpecInputs)
    outputs: BuildSpecOutputs = Field(default_factory=BuildSpecOutputs)
    acceptance_criteria: list[str] = Field(default_factory=list)
```

```python
# backend/onyx/build_runtime/schemas/output_manifest.py
from pydantic import BaseModel, Field


class PreviewEntry(BaseModel):
    url: str
    port: int
    route: str | None = None


class OutputFile(BaseModel):
    path: str
    kind: str  # source / preview / export / asset / log
    size_bytes: int | None = None


class OutputManifest(BaseModel):
    artifact_version: int = 1
    primary_artifact_path: str
    primary_artifact_type: str
    preview_entry: PreviewEntry | None = None
    files: list[OutputFile] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
```

```python
# backend/onyx/build_runtime/schemas/events.py
"""Our own builder-event contract. The in-sandbox launcher normalizes Pi's raw
output into these; PiBuilderAdapter depends ONLY on this contract."""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter


class BuilderStarted(BaseModel):
    type: Literal["builder_started"] = "builder_started"
    at: str


class MessageDelta(BaseModel):
    type: Literal["message_delta"] = "message_delta"
    at: str
    text: str


class FileChanged(BaseModel):
    type: Literal["file_changed"] = "file_changed"
    at: str
    path: str


class PreviewReady(BaseModel):
    type: Literal["preview_ready"] = "preview_ready"
    at: str
    port: int
    route: str | None = None


class ArtifactReady(BaseModel):
    type: Literal["artifact_ready"] = "artifact_ready"
    at: str
    manifest_path: str


class BuildBlocked(BaseModel):
    type: Literal["build_blocked"] = "build_blocked"
    at: str
    reason: str


class BuilderFailed(BaseModel):
    type: Literal["builder_failed"] = "builder_failed"
    at: str
    error: str


class BuilderFinished(BaseModel):
    type: Literal["builder_finished"] = "builder_finished"
    at: str
    success: bool = True


BuilderEvent = Annotated[
    Union[
        BuilderStarted, MessageDelta, FileChanged, PreviewReady,
        ArtifactReady, BuildBlocked, BuilderFailed, BuilderFinished,
    ],
    Field(discriminator="type"),
]

_ADAPTER: TypeAdapter[BuilderEvent] = TypeAdapter(BuilderEvent)


def parse_builder_event(raw: dict) -> BuilderEvent:
    return _ADAPTER.validate_python(raw)
```

```python
# backend/onyx/build_runtime/schemas/build_session.py
from pydantic import BaseModel, Field


class BuildError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict = Field(default_factory=dict)
    occurred_at: str
```

```python
# backend/onyx/build_runtime/schemas/sandbox.py
from pydantic import BaseModel, Field


class SandboxFile(BaseModel):
    path: str
    content: str  # utf-8 text only for sub-project A


class CreateSandboxInput(BaseModel):
    session_id: str
    snapshot: str
    env_vars: dict[str, str] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)


class CreateSandboxResult(BaseModel):
    sandbox_id: str
    status: str


class CommandResult(BaseModel):
    exit_code: int
    stdout: str = ""


class PreviewInfo(BaseModel):
    url: str
    port: int
    token: str | None = None
    route: str | None = None


class SandboxStatusInfo(BaseModel):
    sandbox_id: str
    state: str
```

```python
# backend/onyx/build_runtime/schemas/builder.py
from pydantic import BaseModel, Field


class BuilderConfig(BaseModel):
    model: str | None = None
    timeout_seconds: int | None = None


class StartBuildInput(BaseModel):
    build_session_id: str
    sandbox_id: str
    mode: str = "initial_build"  # initial_build / rebuild
    instruction: str = ""
    builder_config: BuilderConfig = Field(default_factory=BuilderConfig)


class StartBuildResult(BaseModel):
    builder_session_id: str
```

`schemas/__init__.py` 留空。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/unit/build_runtime/test_schemas.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/onyx/build_runtime/schemas/ backend/tests/unit/build_runtime/test_schemas.py
git commit -m "feat(build_runtime): domain pydantic schemas + BuilderEvent contract"
```

---

## Task 3: 枚举 + ORM 表 + Alembic 迁移

**Files:**
- Modify: `backend/onyx/db/enums.py`
- Modify: `backend/onyx/db/models.py`
- Create: `backend/alembic/versions/<rev>_add_build_runtime_tables.py`
- Test: `backend/tests/external_dependency_unit/build_runtime/test_models.py`

**Interfaces:**
- Produces: 枚举 `BuildRuntimeStatus`、`BuildArtifactType`;表 `BuildRuntimeSession`(列见下)、`BuildRuntimeEvent`(`id`,`session_id`,`seq`,`packet_json`,`created_at`)。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/external_dependency_unit/build_runtime/test_models.py
from onyx.db.enums import BuildRuntimeStatus, BuildArtifactType
from onyx.db.models import BuildRuntimeSession, BuildRuntimeEvent


def test_enums_present():
    assert BuildRuntimeStatus.QUEUED.value == "queued"
    assert BuildArtifactType.LANDING_PAGE.value == "landing_page"


def test_tables_have_expected_columns():
    cols = set(BuildRuntimeSession.__table__.columns.keys())
    assert {"id", "user_id", "artifact_type", "status", "spec", "sandbox_id",
            "preview_url", "latest_output", "last_error"}.issubset(cols)
    ev_cols = set(BuildRuntimeEvent.__table__.columns.keys())
    assert {"id", "session_id", "seq", "packet_json"}.issubset(ev_cols)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/external_dependency_unit/build_runtime/test_models.py -v`
Expected: FAIL(`ImportError: cannot import name 'BuildRuntimeStatus'`)

- [ ] **Step 3a: 加枚举**

在 `backend/onyx/db/enums.py` 末尾追加(沿用文件里 `from enum import Enum as PyEnum`):

```python
class BuildRuntimeStatus(str, PyEnum):
    QUEUED = "queued"
    PROVISIONING = "provisioning"
    BUILDING = "building"
    PREVIEW_READY = "preview_ready"
    AWAITING_FEEDBACK = "awaiting_feedback"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"

    def is_terminal(self) -> bool:
        return self in (
            BuildRuntimeStatus.COMPLETED,
            BuildRuntimeStatus.FAILED,
            BuildRuntimeStatus.TERMINATED,
        )


class BuildArtifactType(str, PyEnum):
    LANDING_PAGE = "landing_page"
    SLIDES = "slides"
    REPORT = "report"
    DASHBOARD = "dashboard"
    TOOL = "tool"
```

- [ ] **Step 3b: 加 ORM 表**

在 `backend/onyx/db/models.py` 末尾追加(import 区已有 `Mapped/mapped_column/PGUUID/func/ForeignKey/Integer/String/DateTime/Enum/uuid4/datetime`;`JSONB` 用 `from sqlalchemy.dialects.postgresql import JSONB as PGJSONB`,文件已导入):

```python
class BuildRuntimeSession(Base):
    """build_runtime (Daytona+Pi) delivery session. Parallel to BuildSession
    (opencode Craft); gated by ENABLE_BUILD_RUNTIME."""

    __tablename__ = "build_runtime_session"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    parent_chat_session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    artifact_type: Mapped[BuildArtifactType] = mapped_column(
        Enum(BuildArtifactType, native_enum=False, name="buildartifacttype"),
        nullable=False,
    )
    template_id: Mapped[str] = mapped_column(String, nullable=False)
    template_version: Mapped[str] = mapped_column(String, nullable=False, default="1")
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[BuildRuntimeStatus] = mapped_column(
        Enum(BuildRuntimeStatus, native_enum=False, name="buildruntimestatus"),
        nullable=False,
        default=BuildRuntimeStatus.QUEUED,
    )
    status_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    spec: Mapped[dict] = mapped_column(PGJSONB, nullable=False)
    sandbox_provider: Mapped[str] = mapped_column(String, nullable=False, default="daytona")
    sandbox_id: Mapped[str | None] = mapped_column(String, nullable=True)
    builder_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    preview_url: Mapped[str | None] = mapped_column(String, nullable=True)
    latest_output: Mapped[dict | None] = mapped_column(PGJSONB, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[dict | None] = mapped_column(PGJSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BuildRuntimeEvent(Base):
    """Durable, ordered builder events for a session. Mirrors chat_run_event."""

    __tablename__ = "build_runtime_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("build_runtime_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    packet_json: Mapped[dict] = mapped_column(PGJSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_build_runtime_event_session_seq"),
        Index("ix_build_runtime_event_session_seq", "session_id", "seq"),
    )
```

> 若 `UniqueConstraint`/`Index` 未在 models.py 顶部导入,补 `from sqlalchemy import UniqueConstraint, Index`(文件通常已导入,核对即可)。

- [ ] **Step 3c: 写迁移**

先 `cd backend && alembic revision -m "add build_runtime tables"` 生成空文件,再手写内容(`down_revision` 用生成文件里已填好的值):

```python
"""add build_runtime tables

Revision ID: <生成的>
Revises: <生成的>
Create Date: ...
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "<生成的>"
down_revision = "<生成的>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "build_runtime_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=True),
        sa.Column("parent_chat_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column("template_id", sa.String(), nullable=False),
        sa.Column("template_version", sa.String(), nullable=False, server_default="1"),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("status_reason", sa.String(), nullable=True),
        sa.Column("spec", postgresql.JSONB(), nullable=False),
        sa.Column("sandbox_provider", sa.String(), nullable=False, server_default="daytona"),
        sa.Column("sandbox_id", sa.String(), nullable=True),
        sa.Column("builder_session_id", sa.String(), nullable=True),
        sa.Column("preview_url", sa.String(), nullable=True),
        sa.Column("latest_output", postgresql.JSONB(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_build_runtime_session_user", "build_runtime_session", ["user_id"])
    op.create_table(
        "build_runtime_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("build_runtime_session.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("packet_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("session_id", "seq", name="uq_build_runtime_event_session_seq"),
    )
    op.create_index("ix_build_runtime_event_session_seq", "build_runtime_event", ["session_id", "seq"])


def downgrade() -> None:
    op.drop_index("ix_build_runtime_event_session_seq", table_name="build_runtime_event")
    op.drop_table("build_runtime_event")
    op.drop_index("ix_build_runtime_session_user", table_name="build_runtime_session")
    op.drop_table("build_runtime_session")
```

- [ ] **Step 4: 应用迁移并跑测试**

Run:
```bash
cd backend && alembic upgrade head && cd ..
pytest backend/tests/external_dependency_unit/build_runtime/test_models.py -v
```
Expected: 迁移成功;PASS(2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/onyx/db/enums.py backend/onyx/db/models.py backend/alembic/versions/ backend/tests/external_dependency_unit/build_runtime/test_models.py
git commit -m "feat(build_runtime): add BuildRuntimeSession + BuildRuntimeEvent tables, enums, migration"
```

---

## Task 4: DB 操作模块

**Files:**
- Create: `backend/onyx/db/build_runtime.py`
- Test: `backend/tests/external_dependency_unit/build_runtime/test_db.py`

**Interfaces:**
- Consumes: `BuildRuntimeSession`,`BuildRuntimeEvent`,`BuildRuntimeStatus`,`BuildArtifactType`,`BuildSpec`,`BuildError`,`OutputManifest`,`PreviewInfo`,`parse_builder_event`,`BuilderEvent`。
- Produces:
  - `create_build_runtime_session(db, *, user_id, artifact_type, template_id, spec, title, parent_chat_session_id=None) -> BuildRuntimeSession`
  - `get_build_runtime_session(db, session_id) -> BuildRuntimeSession | None`
  - `update_status(db, session_id, status, reason=None) -> None`
  - `attach_sandbox(db, session_id, sandbox_id) -> None`
  - `attach_builder(db, session_id, builder_session_id) -> None`
  - `set_preview(db, session_id, preview: PreviewInfo) -> None`
  - `set_output(db, session_id, output: OutputManifest) -> None`
  - `set_failed(db, session_id, error: BuildError) -> None`
  - `append_build_event(db, session_id, event: BuilderEvent) -> int`(返回 seq)
  - `fetch_build_events_after(db, session_id, after_seq: int) -> list[tuple[int, BuilderEvent]]`

- [ ] **Step 1: 写失败测试**(使用 `db_session` fixture,见 `backend/tests/external_dependency_unit/conftest.py`)

```python
# backend/tests/external_dependency_unit/build_runtime/test_db.py
import uuid
from onyx.db.enums import BuildArtifactType, BuildRuntimeStatus
from onyx.build_runtime.schemas.build_spec import BuildSpec
from onyx.build_runtime.schemas.events import PreviewReady
from onyx.db.build_runtime import (
    create_build_runtime_session, get_build_runtime_session, update_status,
    append_build_event, fetch_build_events_after,
)


def test_create_and_status(db_session):
    s = create_build_runtime_session(
        db_session, user_id=None, artifact_type=BuildArtifactType.LANDING_PAGE,
        template_id="landing_page", spec=BuildSpec(title="t", goal="g"), title="t",
    )
    update_status(db_session, s.id, BuildRuntimeStatus.BUILDING)
    again = get_build_runtime_session(db_session, s.id)
    assert again.status == BuildRuntimeStatus.BUILDING
    assert again.spec["title"] == "t"


def test_events_seq_monotonic(db_session):
    s = create_build_runtime_session(
        db_session, user_id=None, artifact_type=BuildArtifactType.LANDING_PAGE,
        template_id="landing_page", spec=BuildSpec(title="t", goal="g"), title="t",
    )
    seq1 = append_build_event(db_session, s.id, PreviewReady(at="x", port=3000))
    seq2 = append_build_event(db_session, s.id, PreviewReady(at="y", port=3001))
    assert (seq1, seq2) == (1, 2)
    rows = fetch_build_events_after(db_session, s.id, after_seq=1)
    assert len(rows) == 1 and rows[0][1].port == 3001
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/external_dependency_unit/build_runtime/test_db.py -v`
Expected: FAIL(`ModuleNotFoundError: onyx.db.build_runtime`)

- [ ] **Step 3: 实现 DB 操作**

```python
# backend/onyx/db/build_runtime.py
"""DB operations for build_runtime sessions and events.

All build_runtime persistence goes through here (CLAUDE.md: db ops under onyx/db).
"""
import json
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from onyx.build_runtime.schemas.build_session import BuildError
from onyx.build_runtime.schemas.build_spec import BuildSpec
from onyx.build_runtime.schemas.events import BuilderEvent, parse_builder_event
from onyx.build_runtime.schemas.output_manifest import OutputManifest
from onyx.build_runtime.schemas.sandbox import PreviewInfo
from onyx.db.enums import BuildArtifactType, BuildRuntimeStatus
from onyx.db.models import BuildRuntimeEvent, BuildRuntimeSession


def _dump(model) -> dict:
    return json.loads(model.model_dump_json())


def create_build_runtime_session(
    db_session: Session,
    *,
    user_id: UUID | None,
    artifact_type: BuildArtifactType,
    template_id: str,
    spec: BuildSpec,
    title: str | None,
    parent_chat_session_id: UUID | None = None,
) -> BuildRuntimeSession:
    session = BuildRuntimeSession(
        user_id=user_id,
        parent_chat_session_id=parent_chat_session_id,
        artifact_type=artifact_type,
        template_id=template_id,
        title=title,
        status=BuildRuntimeStatus.QUEUED,
        spec=_dump(spec),
    )
    db_session.add(session)
    db_session.commit()
    return session


def get_build_runtime_session(
    db_session: Session, session_id: UUID
) -> BuildRuntimeSession | None:
    return db_session.scalar(
        select(BuildRuntimeSession).where(BuildRuntimeSession.id == session_id)
    )


def update_status(
    db_session: Session, session_id: UUID,
    status: BuildRuntimeStatus, reason: str | None = None,
) -> None:
    session = get_build_runtime_session(db_session, session_id)
    if session is None:
        return
    session.status = status
    if reason is not None:
        session.status_reason = reason
    if status == BuildRuntimeStatus.COMPLETED:
        session.completed_at = func.now()
    db_session.commit()


def attach_sandbox(db_session: Session, session_id: UUID, sandbox_id: str) -> None:
    session = get_build_runtime_session(db_session, session_id)
    if session:
        session.sandbox_id = sandbox_id
        db_session.commit()


def attach_builder(db_session: Session, session_id: UUID, builder_session_id: str) -> None:
    session = get_build_runtime_session(db_session, session_id)
    if session:
        session.builder_session_id = builder_session_id
        db_session.commit()


def set_preview(db_session: Session, session_id: UUID, preview: PreviewInfo) -> None:
    session = get_build_runtime_session(db_session, session_id)
    if session:
        session.preview_url = preview.url
        db_session.commit()


def set_output(db_session: Session, session_id: UUID, output: OutputManifest) -> None:
    session = get_build_runtime_session(db_session, session_id)
    if session:
        session.latest_output = _dump(output)
        db_session.commit()


def set_failed(db_session: Session, session_id: UUID, error: BuildError) -> None:
    session = get_build_runtime_session(db_session, session_id)
    if session:
        session.status = BuildRuntimeStatus.FAILED
        session.last_error = _dump(error)
        db_session.commit()


def append_build_event(
    db_session: Session, session_id: UUID, event: BuilderEvent
) -> int:
    next_seq = (
        db_session.scalar(
            select(func.coalesce(func.max(BuildRuntimeEvent.seq), 0)).where(
                BuildRuntimeEvent.session_id == session_id
            )
        )
        or 0
    ) + 1
    db_session.add(
        BuildRuntimeEvent(
            session_id=session_id, seq=next_seq,
            packet_json=json.loads(event.model_dump_json()),
        )
    )
    db_session.commit()
    return next_seq


def fetch_build_events_after(
    db_session: Session, session_id: UUID, after_seq: int
) -> list[tuple[int, BuilderEvent]]:
    rows = db_session.scalars(
        select(BuildRuntimeEvent)
        .where(
            BuildRuntimeEvent.session_id == session_id,
            BuildRuntimeEvent.seq > after_seq,
        )
        .order_by(BuildRuntimeEvent.seq)
    ).all()
    return [(r.seq, parse_builder_event(r.packet_json)) for r in rows]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/external_dependency_unit/build_runtime/test_db.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/onyx/db/build_runtime.py backend/tests/external_dependency_unit/build_runtime/test_db.py
git commit -m "feat(build_runtime): db operations for sessions and ordered events"
```

---

## Task 5: Provider/Adapter 接口(Protocol)+ 测试替身(Fakes)

**Files:**
- Create: `backend/onyx/build_runtime/interfaces/__init__.py`, `sandbox_provider.py`, `builder_adapter.py`
- Create: `backend/onyx/build_runtime/testing/__init__.py`, `fakes.py`
- Test: `backend/tests/unit/build_runtime/test_fakes.py`

**Interfaces:**
- Consumes: Task 2 的所有 schemas。
- Produces:
  - `SandboxProvider` Protocol:`create_sandbox(input: CreateSandboxInput) -> CreateSandboxResult`、`write_files(sandbox_id, files: list[SandboxFile]) -> None`、`read_file(sandbox_id, path: str) -> str`、`run_command(sandbox_id, command: str, cwd=None) -> CommandResult`、`expose_preview(sandbox_id, port: int) -> PreviewInfo`、`stop_sandbox(sandbox_id) -> None`、`delete_sandbox(sandbox_id) -> None`
  - `BuilderAdapter` Protocol:`start_build(input: StartBuildInput) -> StartBuildResult`、`subscribe(builder_session_id: str) -> Iterator[BuilderEvent]`、`stop(builder_session_id: str) -> None`
  - `FakeSandboxProvider`(可注入 preview),`FakeBuilderAdapter`(可注入 scripted events 列表)

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/build_runtime/test_fakes.py
from onyx.build_runtime.schemas.builder import StartBuildInput
from onyx.build_runtime.schemas.events import BuilderFinished, PreviewReady
from onyx.build_runtime.schemas.sandbox import CreateSandboxInput
from onyx.build_runtime.testing.fakes import FakeBuilderAdapter, FakeSandboxProvider


def test_fake_provider_create_and_preview():
    p = FakeSandboxProvider(preview_url="http://preview.local")
    res = p.create_sandbox(CreateSandboxInput(session_id="s", snapshot="snap"))
    assert res.sandbox_id.startswith("fake-")
    assert p.expose_preview(res.sandbox_id, 3000).url == "http://preview.local"


def test_fake_adapter_scripts_events():
    events = [PreviewReady(at="x", port=3000), BuilderFinished(at="y", success=True)]
    a = FakeBuilderAdapter(scripted_events=events)
    start = a.start_build(StartBuildInput(build_session_id="b", sandbox_id="sb"))
    got = list(a.subscribe(start.builder_session_id))
    assert [e.type for e in got] == ["preview_ready", "builder_finished"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/unit/build_runtime/test_fakes.py -v`
Expected: FAIL(`ModuleNotFoundError: onyx.build_runtime.testing.fakes`)

- [ ] **Step 3: 写 Protocol + Fakes**

```python
# backend/onyx/build_runtime/interfaces/sandbox_provider.py
from typing import Protocol

from onyx.build_runtime.schemas.sandbox import (
    CommandResult, CreateSandboxInput, CreateSandboxResult, PreviewInfo, SandboxFile,
)


class SandboxProvider(Protocol):
    def create_sandbox(self, input: CreateSandboxInput) -> CreateSandboxResult: ...
    def write_files(self, sandbox_id: str, files: list[SandboxFile]) -> None: ...
    def read_file(self, sandbox_id: str, path: str) -> str: ...
    def run_command(self, sandbox_id: str, command: str, cwd: str | None = None) -> CommandResult: ...
    def expose_preview(self, sandbox_id: str, port: int) -> PreviewInfo: ...
    def stop_sandbox(self, sandbox_id: str) -> None: ...
    def delete_sandbox(self, sandbox_id: str) -> None: ...
```

```python
# backend/onyx/build_runtime/interfaces/builder_adapter.py
from collections.abc import Iterator
from typing import Protocol

from onyx.build_runtime.schemas.builder import StartBuildInput, StartBuildResult
from onyx.build_runtime.schemas.events import BuilderEvent


class BuilderAdapter(Protocol):
    def start_build(self, input: StartBuildInput) -> StartBuildResult: ...
    def subscribe(self, builder_session_id: str) -> Iterator[BuilderEvent]: ...
    def stop(self, builder_session_id: str) -> None: ...
```

```python
# backend/onyx/build_runtime/testing/fakes.py
"""In-memory test doubles for SandboxProvider / BuilderAdapter."""
from collections.abc import Iterator

from onyx.build_runtime.schemas.builder import StartBuildInput, StartBuildResult
from onyx.build_runtime.schemas.events import BuilderEvent
from onyx.build_runtime.schemas.sandbox import (
    CommandResult, CreateSandboxInput, CreateSandboxResult, PreviewInfo, SandboxFile,
)


class FakeSandboxProvider:
    def __init__(self, preview_url: str = "http://preview.local", read_payload: str = "{}"):
        self.preview_url = preview_url
        self.read_payload = read_payload
        self.written: dict[str, list[SandboxFile]] = {}
        self.deleted: list[str] = []
        self._counter = 0

    def create_sandbox(self, input: CreateSandboxInput) -> CreateSandboxResult:
        self._counter += 1
        return CreateSandboxResult(sandbox_id=f"fake-{self._counter}", status="started")

    def write_files(self, sandbox_id: str, files: list[SandboxFile]) -> None:
        self.written.setdefault(sandbox_id, []).extend(files)

    def read_file(self, sandbox_id: str, path: str) -> str:
        return self.read_payload

    def run_command(self, sandbox_id: str, command: str, cwd: str | None = None) -> CommandResult:
        return CommandResult(exit_code=0, stdout="")

    def expose_preview(self, sandbox_id: str, port: int) -> PreviewInfo:
        return PreviewInfo(url=self.preview_url, port=port)

    def stop_sandbox(self, sandbox_id: str) -> None:
        pass

    def delete_sandbox(self, sandbox_id: str) -> None:
        self.deleted.append(sandbox_id)


class FakeBuilderAdapter:
    def __init__(self, scripted_events: list[BuilderEvent]):
        self.scripted_events = scripted_events
        self.stopped = False

    def start_build(self, input: StartBuildInput) -> StartBuildResult:
        return StartBuildResult(builder_session_id=f"builder-{input.sandbox_id}")

    def subscribe(self, builder_session_id: str) -> Iterator[BuilderEvent]:
        yield from self.scripted_events

    def stop(self, builder_session_id: str) -> None:
        self.stopped = True
```

`interfaces/__init__.py`、`testing/__init__.py` 留空。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/unit/build_runtime/test_fakes.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/onyx/build_runtime/interfaces/ backend/onyx/build_runtime/testing/ backend/tests/unit/build_runtime/test_fakes.py
git commit -m "feat(build_runtime): SandboxProvider/BuilderAdapter protocols + fakes"
```

---

## Task 6: 错误码 + LLMFlow + TemplateService + 落地页模板资产

**Files:**
- Modify: `backend/onyx/error_handling/error_codes.py`
- Modify: `backend/onyx/tracing/flows.py`
- Create: `backend/onyx/build_runtime/services/__init__.py`, `template_service.py`
- Create: `backend/onyx/build_runtime/templates/landing_page/AGENTS.md`, `SYSTEM.md`, `output_contract.md`
- Test: `backend/tests/unit/build_runtime/test_template_service.py`

**Interfaces:**
- Produces:
  - `OnyxErrorCode.BUILD_PROVISION_FAILED = ("BUILD_PROVISION_FAILED", 502)`、`BUILDER_FAILED = ("BUILDER_FAILED", 502)`、`BUILD_SESSION_NOT_FOUND = ("BUILD_SESSION_NOT_FOUND", 404)`
  - `LLMFlow.BUILD_SPEC_GENERATION = "build_spec_generation"`
  - `TemplateDescriptor`(`template_id:str`,`artifact_type:BuildArtifactType`,`snapshot:str`,`preview_port:int`,`agents_md:str`,`system_md:str`,`output_contract:str`)
  - `TemplateService.resolve(artifact_type: BuildArtifactType) -> TemplateDescriptor`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/build_runtime/test_template_service.py
from onyx.db.enums import BuildArtifactType
from onyx.build_runtime.services.template_service import TemplateService
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.tracing.flows import LLMFlow


def test_resolve_landing_page():
    desc = TemplateService().resolve(BuildArtifactType.LANDING_PAGE)
    assert desc.snapshot == "glomi-landing-page"
    assert desc.preview_port == 3000
    assert "AGENTS" in desc.agents_md or len(desc.agents_md) > 0


def test_new_error_codes_and_flow_exist():
    assert OnyxErrorCode.BUILD_PROVISION_FAILED.status_code == 502
    assert LLMFlow.BUILD_SPEC_GENERATION.value == "build_spec_generation"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/unit/build_runtime/test_template_service.py -v`
Expected: FAIL(`AttributeError: BUILD_PROVISION_FAILED` 或模块缺失)

- [ ] **Step 3a: 加错误码**(在 `error_codes.py` 合适分区追加)

```python
    # Build runtime (502 / 404)
    BUILD_PROVISION_FAILED = ("BUILD_PROVISION_FAILED", 502)
    BUILDER_FAILED = ("BUILDER_FAILED", 502)
    BUILD_SESSION_NOT_FOUND = ("BUILD_SESSION_NOT_FOUND", 404)
```

- [ ] **Step 3b: 加 LLMFlow**(在 `flows.py` 的 `LLMFlow` 类里追加一行)

```python
    BUILD_SPEC_GENERATION = "build_spec_generation"
```

- [ ] **Step 3c: 写模板资产**

`backend/onyx/build_runtime/templates/landing_page/AGENTS.md`:
```markdown
# Landing Page Builder — Operating Rules

You are a focused front-end builder running inside an isolated sandbox.
Your job: build ONE production-quality Chinese landing page (中文落地页).

- Work only inside `/workspace/src` (a pre-scaffolded Next.js + Tailwind + shadcn app).
- Read the task at `/workspace/input/task.json`. Honor every acceptance criterion.
- Include: Hero、核心卖点、FAQ、CTA;移动端适配;文案为中文。
- Do NOT add a backend, auth, or external network calls.
- When done, ensure `bun run dev` serves the page on port 3000.
- Write the output manifest to `/workspace/out/output_manifest.json` per output_contract.md.
```

`backend/onyx/build_runtime/templates/landing_page/SYSTEM.md`:
```markdown
# System Notes

- Runtime: Node + bun + Next.js (app router) + Tailwind + shadcn/ui, pre-installed.
- Keep edits minimal and cohesive; prefer editing app/page.tsx and components/.
- The preview server must bind 0.0.0.0:3000.
```

`backend/onyx/build_runtime/templates/landing_page/output_contract.md`:
```markdown
# Output Contract

On success, write `/workspace/out/output_manifest.json`:

{
  "artifact_version": 1,
  "primary_artifact_path": "/workspace/src",
  "primary_artifact_type": "landing_page",
  "preview_entry": {"url": "", "port": 3000, "route": "/"},
  "files": [{"path": "/workspace/src/app/page.tsx", "kind": "source"}],
  "notes": []
}
```

- [ ] **Step 3d: 写 TemplateService**

```python
# backend/onyx/build_runtime/services/template_service.py
from pathlib import Path

from pydantic import BaseModel

from onyx.build_runtime.configs import SANDBOX_PREVIEW_PORT
from onyx.db.enums import BuildArtifactType

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class TemplateDescriptor(BaseModel):
    template_id: str
    artifact_type: BuildArtifactType
    snapshot: str
    preview_port: int
    agents_md: str
    system_md: str
    output_contract: str


def _read(template_dir: Path, name: str) -> str:
    return (template_dir / name).read_text(encoding="utf-8")


class TemplateService:
    """Resolves an artifact type to its template descriptor. Sub-project A ships
    only landing_page; later sub-projects register more."""

    def resolve(self, artifact_type: BuildArtifactType) -> TemplateDescriptor:
        if artifact_type != BuildArtifactType.LANDING_PAGE:
            raise ValueError(f"No template for artifact_type={artifact_type} in sub-project A")
        d = _TEMPLATES_DIR / "landing_page"
        return TemplateDescriptor(
            template_id="landing_page",
            artifact_type=BuildArtifactType.LANDING_PAGE,
            snapshot="glomi-landing-page",
            preview_port=SANDBOX_PREVIEW_PORT,
            agents_md=_read(d, "AGENTS.md"),
            system_md=_read(d, "SYSTEM.md"),
            output_contract=_read(d, "output_contract.md"),
        )
```

`services/__init__.py` 留空。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/unit/build_runtime/test_template_service.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/onyx/error_handling/error_codes.py backend/onyx/tracing/flows.py backend/onyx/build_runtime/services/ backend/onyx/build_runtime/templates/ backend/tests/unit/build_runtime/test_template_service.py
git commit -m "feat(build_runtime): error codes, LLMFlow, TemplateService + landing_page assets"
```

---

## Task 7: BuildOrchestrator 状态机(核心)

**Files:**
- Create: `backend/onyx/build_runtime/services/build_orchestrator.py`
- Test: `backend/tests/unit/build_runtime/test_orchestrator.py`

**Interfaces:**
- Consumes: `SandboxProvider`,`BuilderAdapter`,`TemplateService`,Task 4 的所有 DB 函数,所有 schemas/events,`build_runtime.configs`。
- Produces: `BuildOrchestrator(db_session, provider, adapter, template_service)`,方法 `run(session_id: UUID) -> None`。`run` 内部:更新状态、起沙箱、写 context 文件、起 builder、消费 `subscribe()` 事件、`append_build_event` 持久化、遇 `PreviewReady` 调 `expose_preview` + `set_preview`、遇 `ArtifactReady` 读 manifest + `set_output`、遇 `BuilderFinished` 置 `completed`、遇 `BuilderFailed`/异常 `set_failed` + `delete_sandbox`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/build_runtime/test_orchestrator.py
import uuid
import pytest
from onyx.db.enums import BuildArtifactType, BuildRuntimeStatus
from onyx.build_runtime.schemas.build_spec import BuildSpec
from onyx.build_runtime.schemas.events import (
    BuilderStarted, PreviewReady, ArtifactReady, BuilderFinished, BuilderFailed,
)
from onyx.build_runtime.testing.fakes import FakeBuilderAdapter, FakeSandboxProvider
from onyx.build_runtime.services.build_orchestrator import BuildOrchestrator
from onyx.build_runtime.services.template_service import TemplateService
from onyx.db.build_runtime import (
    create_build_runtime_session, get_build_runtime_session, fetch_build_events_after,
)

MANIFEST = '{"artifact_version":1,"primary_artifact_path":"/workspace/src","primary_artifact_type":"landing_page","files":[],"notes":[]}'


def _make_session(db_session):
    return create_build_runtime_session(
        db_session, user_id=None, artifact_type=BuildArtifactType.LANDING_PAGE,
        template_id="landing_page", spec=BuildSpec(title="t", goal="g"), title="t",
    )


def test_happy_path_reaches_completed(db_session):
    s = _make_session(db_session)
    events = [
        BuilderStarted(at="0"),
        PreviewReady(at="1", port=3000),
        ArtifactReady(at="2", manifest_path="/workspace/out/output_manifest.json"),
        BuilderFinished(at="3", success=True),
    ]
    provider = FakeSandboxProvider(preview_url="http://preview.local", read_payload=MANIFEST)
    adapter = FakeBuilderAdapter(scripted_events=events)
    BuildOrchestrator(db_session, provider, adapter, TemplateService()).run(s.id)

    again = get_build_runtime_session(db_session, s.id)
    assert again.status == BuildRuntimeStatus.COMPLETED
    assert again.preview_url == "http://preview.local"
    assert again.sandbox_id is not None
    assert again.latest_output["primary_artifact_type"] == "landing_page"
    # events persisted (>=4)
    assert len(fetch_build_events_after(db_session, s.id, after_seq=0)) >= 4


def test_builder_failure_marks_failed_and_cleans_up(db_session):
    s = _make_session(db_session)
    events = [BuilderStarted(at="0"), BuilderFailed(at="1", error="boom")]
    provider = FakeSandboxProvider()
    adapter = FakeBuilderAdapter(scripted_events=events)
    BuildOrchestrator(db_session, provider, adapter, TemplateService()).run(s.id)

    again = get_build_runtime_session(db_session, s.id)
    assert again.status == BuildRuntimeStatus.FAILED
    assert again.last_error["message"] == "boom"
    assert provider.deleted  # sandbox cleaned up
```

> 该测试用真实 PG(`db_session` fixture),因此放在 external_dependency。把文件移到 `backend/tests/external_dependency_unit/build_runtime/test_orchestrator.py`,provider/adapter 仍是内存 fake。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/external_dependency_unit/build_runtime/test_orchestrator.py -v`
Expected: FAIL(`ModuleNotFoundError: build_orchestrator`)

- [ ] **Step 3: 实现 orchestrator**

```python
# backend/onyx/build_runtime/services/build_orchestrator.py
"""Drives one build_runtime session through its state machine.

Pure orchestration + relay: creates a sandbox via SandboxProvider, starts the
builder via BuilderAdapter, consumes the builder's BuilderEvent stream, persists
events + status transitions. Runs inside a Celery task with its own db session.
"""
import json
from datetime import datetime, timezone
from uuid import UUID

from onyx.build_runtime.interfaces.builder_adapter import BuilderAdapter
from onyx.build_runtime.interfaces.sandbox_provider import SandboxProvider
from onyx.build_runtime.schemas.build_session import BuildError
from onyx.build_runtime.schemas.build_spec import BuildSpec
from onyx.build_runtime.schemas.builder import StartBuildInput
from onyx.build_runtime.schemas.events import (
    ArtifactReady, BuilderFailed, BuilderFinished, PreviewReady,
)
from onyx.build_runtime.schemas.output_manifest import OutputManifest
from onyx.build_runtime.schemas.sandbox import CreateSandboxInput, SandboxFile
from onyx.build_runtime.services.template_service import TemplateService
from onyx.db.build_runtime import (
    append_build_event, attach_builder, attach_sandbox, get_build_runtime_session,
    set_failed, set_output, set_preview, update_status,
)
from onyx.db.enums import BuildRuntimeStatus
from onyx.utils.logger import setup_logger
from sqlalchemy.orm import Session

logger = setup_logger()


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class BuildOrchestrator:
    def __init__(
        self,
        db_session: Session,
        provider: SandboxProvider,
        adapter: BuilderAdapter,
        template_service: TemplateService,
    ) -> None:
        self.db = db_session
        self.provider = provider
        self.adapter = adapter
        self.template_service = template_service

    def run(self, session_id: UUID) -> None:
        session = get_build_runtime_session(self.db, session_id)
        if session is None:
            logger.error("build_runtime session %s not found", session_id)
            return
        sandbox_id: str | None = None
        try:
            spec = BuildSpec.model_validate(session.spec)
            template = self.template_service.resolve(session.artifact_type)

            update_status(self.db, session_id, BuildRuntimeStatus.PROVISIONING)
            create = self.provider.create_sandbox(
                CreateSandboxInput(
                    session_id=str(session_id),
                    snapshot=template.snapshot,
                    labels={"session_id": str(session_id)},
                )
            )
            sandbox_id = create.sandbox_id
            attach_sandbox(self.db, session_id, sandbox_id)

            self.provider.write_files(
                sandbox_id,
                [
                    SandboxFile(path="/workspace/input/task.json",
                                content=json.dumps(self._task_json(spec, template.template_id), ensure_ascii=False)),
                    SandboxFile(path="/workspace/context/AGENTS.md", content=template.agents_md),
                    SandboxFile(path="/workspace/context/SYSTEM.md", content=template.system_md),
                ],
            )

            update_status(self.db, session_id, BuildRuntimeStatus.BUILDING)
            start = self.adapter.start_build(
                StartBuildInput(build_session_id=str(session_id), sandbox_id=sandbox_id)
            )
            attach_builder(self.db, session_id, start.builder_session_id)

            for event in self.adapter.subscribe(start.builder_session_id):
                append_build_event(self.db, session_id, event)

                if isinstance(event, PreviewReady):
                    preview = self.provider.expose_preview(sandbox_id, event.port)
                    set_preview(self.db, session_id, preview)
                    update_status(self.db, session_id, BuildRuntimeStatus.PREVIEW_READY)

                elif isinstance(event, ArtifactReady):
                    raw = self.provider.read_file(sandbox_id, event.manifest_path)
                    set_output(self.db, session_id, OutputManifest.model_validate_json(raw))

                elif isinstance(event, BuilderFinished):
                    update_status(self.db, session_id, BuildRuntimeStatus.COMPLETED)
                    return

                elif isinstance(event, BuilderFailed):
                    self._fail(session_id, event.error, sandbox_id)
                    return

            # stream ended without a terminal event
            self._fail(session_id, "builder stream ended without completion", sandbox_id)
        except Exception as e:  # noqa: BLE001 — orchestrator is the boundary
            logger.exception("build_runtime session %s crashed", session_id)
            self._fail(session_id, str(e), sandbox_id)

    def _fail(self, session_id: UUID, message: str, sandbox_id: str | None) -> None:
        set_failed(
            self.db, session_id,
            BuildError(code="BUILDER_FAILED", message=message, occurred_at=_now()),
        )
        if sandbox_id:
            try:
                self.provider.delete_sandbox(sandbox_id)
            except Exception:
                logger.exception("failed cleaning sandbox %s", sandbox_id)

    @staticmethod
    def _task_json(spec: BuildSpec, template_id: str) -> dict:
        return {
            "template_id": template_id,
            "title": spec.title,
            "goal": spec.goal,
            "requirements": spec.requirements,
            "acceptance_criteria": spec.acceptance_criteria,
            "visual_style": spec.visual_style,
        }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/external_dependency_unit/build_runtime/test_orchestrator.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/onyx/build_runtime/services/build_orchestrator.py backend/tests/external_dependency_unit/build_runtime/test_orchestrator.py
git commit -m "feat(build_runtime): BuildOrchestrator state machine (core, fake-tested)"
```

---

## Task 8: SpecBuilder(NL → BuildSpec)

**Files:**
- Create: `backend/onyx/build_runtime/services/spec_builder.py`
- Test: `backend/tests/unit/build_runtime/test_spec_builder.py`(fake LLM)
- Test: `backend/tests/external_dependency_unit/build_runtime/test_spec_builder_llm.py`(真实 gpt-5-mini,gated)

**Interfaces:**
- Consumes: `BuildSpec`,`LLMFlow.BUILD_SPEC_GENERATION`,`llm_generation_span`,`LLM` 接口(`invoke(..., structured_response_format=...)`)。
- Produces: `SpecBuilder(llm)`,方法 `build(nl_request: str, artifact_type: BuildArtifactType) -> BuildSpec`。

- [ ] **Step 1: 写失败测试(fake LLM)**

```python
# backend/tests/unit/build_runtime/test_spec_builder.py
from types import SimpleNamespace
from onyx.db.enums import BuildArtifactType
from onyx.build_runtime.services.spec_builder import SpecBuilder


class _FakeLLM:
    def invoke(self, prompt, structured_response_format=None, **kwargs):
        content = '{"title":"产品发布页","goal":"中文落地页","requirements":["Hero","CTA"],"acceptance_criteria":["可预览"],"visual_style":["科技感"]}'
        return SimpleNamespace(choice=SimpleNamespace(message=SimpleNamespace(content=content)))


def test_build_parses_structured_output():
    spec = SpecBuilder(_FakeLLM()).build("帮我做一个产品发布页", BuildArtifactType.LANDING_PAGE)
    assert spec.title == "产品发布页"
    assert "Hero" in spec.requirements
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/unit/build_runtime/test_spec_builder.py -v`
Expected: FAIL(模块缺失)

- [ ] **Step 3: 实现 SpecBuilder**

```python
# backend/onyx/build_runtime/services/spec_builder.py
"""Turns a natural-language delivery request into a structured BuildSpec."""
from onyx.build_runtime.schemas.build_spec import BuildSpec
from onyx.db.enums import BuildArtifactType
from onyx.llm.interfaces import LLM
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import llm_generation_span
from onyx.tracing.llm_utils import record_llm_response

_SYSTEM = (
    "你是交付需求规格化助手。把用户的中文交付需求转成 JSON BuildSpec。"
    "只输出 JSON,字段:title, goal, target_audience, requirements[], "
    "constraints[], visual_style[], acceptance_criteria[]。"
)

_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "build_spec",
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "goal": {"type": "string"},
                "target_audience": {"type": ["string", "null"]},
                "requirements": {"type": "array", "items": {"type": "string"}},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "visual_style": {"type": "array", "items": {"type": "string"}},
                "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "goal"],
        },
    },
}


class SpecBuilder:
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def build(self, nl_request: str, artifact_type: BuildArtifactType) -> BuildSpec:
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"交付物类型:{artifact_type.value}\n需求:{nl_request}"},
        ]
        with llm_generation_span(
            llm=self.llm, flow=LLMFlow.BUILD_SPEC_GENERATION, input_messages=messages,
        ) as span:
            response = self.llm.invoke(prompt=messages, structured_response_format=_SCHEMA)
            record_llm_response(span, response)
        content = response.choice.message.content
        return BuildSpec.model_validate_json(content)
```

> 核对 `record_llm_response` 的导入路径(Task 研究里它与 `llm_generation_span` 同域;若在 `onyx.tracing.llm_utils` 之外,按实际导入)。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/unit/build_runtime/test_spec_builder.py -v`
Expected: PASS(1 passed)

- [ ] **Step 5: 加真实 LLM 测试(gated)**

```python
# backend/tests/external_dependency_unit/build_runtime/test_spec_builder_llm.py
import os
import pytest
from onyx.db.enums import BuildArtifactType
from onyx.build_runtime.services.spec_builder import SpecBuilder
from onyx.llm.factory import get_default_llm


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="needs OpenAI key")
def test_real_llm_produces_valid_spec():
    # 需要 .vscode/.env 里有可用 provider;模型用 gpt-5-mini
    spec = SpecBuilder(get_default_llm()).build(
        "帮我做一个面向年轻人的国潮咖啡品牌中文落地页", BuildArtifactType.LANDING_PAGE
    )
    assert spec.title and spec.goal
```

Run: `python -m dotenv -f .vscode/.env run -- pytest backend/tests/external_dependency_unit/build_runtime/test_spec_builder_llm.py -v`
Expected: PASS(或无 key 时 skip)

- [ ] **Step 6: Commit**

```bash
git add backend/onyx/build_runtime/services/spec_builder.py backend/tests/unit/build_runtime/test_spec_builder.py backend/tests/external_dependency_unit/build_runtime/test_spec_builder_llm.py
git commit -m "feat(build_runtime): SpecBuilder (NL->BuildSpec) with BUILD_SPEC_GENERATION flow"
```

---

## Task 9: 沙箱镜像 + 沙箱内 launcher(归一化 Pi → BuilderEvent JSONL)

**Files:**
- Create: `backend/onyx/build_runtime/sandbox_image/Dockerfile`
- Create: `backend/onyx/build_runtime/sandbox_image/run_build.py`
- Create: `backend/onyx/build_runtime/sandbox_image/write_models_json.py`
- Test: `backend/tests/unit/build_runtime/test_run_build_normalization.py`

**Interfaces:**
- Produces:
  - 一个 `glomi-landing-page` OCI 镜像(Node + bun + Next.js 模板 + Pi + python3),含 `/opt/glomi/run_build.py`、`/opt/glomi/write_models_json.py`、预脚手架 `/workspace/src`。
  - `run_build.py` 契约:读 `/workspace/input/task.json`,写 `~/.pi/agent/models.json`(从 env `GLOMI_LLM_BASE_URL/GLOMI_LLM_API_KEY/GLOMI_LLM_MODEL`),detached 跑 Pi,把 Pi 事件归一化成 BuilderEvent,**逐行 append 到 `/workspace/logs/events.jsonl`**;成功时起 `bun run dev`(port 3000)并写 `preview_ready` + `/workspace/out/output_manifest.json` + `artifact_ready` + `builder_finished`;失败写 `builder_failed`。
  - 可单元测试的纯函数 `normalize_pi_event(raw: dict) -> dict | None`(放 run_build.py 内,import 可测)。

- [ ] **Step 1: 写失败测试(只测归一化纯函数)**

```python
# backend/tests/unit/build_runtime/test_run_build_normalization.py
import importlib.util, pathlib

_spec = importlib.util.spec_from_file_location(
    "glomi_run_build",
    pathlib.Path("backend/onyx/build_runtime/sandbox_image/run_build.py"),
)
run_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_build)


def test_normalize_text_delta():
    out = run_build.normalize_pi_event(
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "hi"}}
    )
    assert out["type"] == "message_delta" and out["text"] == "hi"


def test_normalize_agent_end_is_dropped():
    # agent_end is handled by launcher flow, not emitted verbatim
    assert run_build.normalize_pi_event({"type": "agent_end", "messages": []}) is None


def test_normalize_unknown_dropped():
    assert run_build.normalize_pi_event({"type": "whatever"}) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/unit/build_runtime/test_run_build_normalization.py -v`
Expected: FAIL(文件不存在)

- [ ] **Step 3a: 写 launcher**

```python
# backend/onyx/build_runtime/sandbox_image/run_build.py
"""In-sandbox build launcher. Runs Pi, normalizes its raw JSON events into our
BuilderEvent JSONL contract, appended line-by-line to /workspace/logs/events.jsonl.

This file runs INSIDE the glomi-landing-page sandbox (python3), not in the API.
Keep it dependency-free (stdlib only)."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

EVENTS = "/workspace/logs/events.jsonl"
SRC = "/workspace/src"
OUT_MANIFEST = "/workspace/out/output_manifest.json"
PREVIEW_PORT = 3000


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def emit(event: dict) -> None:
    os.makedirs("/workspace/logs", exist_ok=True)
    with open(EVENTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def normalize_pi_event(raw: dict) -> dict | None:
    """Map a raw Pi RPC/json event to our BuilderEvent dict, or None to drop."""
    t = raw.get("type")
    if t == "agent_start":
        return {"type": "builder_started", "at": _now()}
    if t == "message_update":
        ame = raw.get("assistantMessageEvent") or {}
        if ame.get("type") == "text_delta":
            return {"type": "message_delta", "at": _now(), "text": ame.get("delta", "")}
        return None
    return None  # agent_end + everything else handled by launcher flow


def _build_prompt() -> str:
    task = json.load(open("/workspace/input/task.json", encoding="utf-8"))
    agents = open("/workspace/context/AGENTS.md", encoding="utf-8").read()
    return (
        f"{agents}\n\n# Task\n{json.dumps(task, ensure_ascii=False, indent=2)}\n\n"
        "构建落地页,完成后确保 port 3000 可预览。"
    )


def main() -> int:
    emit({"type": "builder_started", "at": _now()})
    # 1) write models.json from env
    subprocess.run([sys.executable, "/opt/glomi/write_models_json.py"], check=True)
    # 2) run Pi in json mode, normalize streamed events
    proc = subprocess.Popen(
        ["pi", "-p", _build_prompt(), "--mode", "json"],
        cwd=SRC, stdout=subprocess.PIPE, text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        norm = normalize_pi_event(raw)
        if norm:
            emit(norm)
    code = proc.wait()
    if code != 0:
        emit({"type": "builder_failed", "at": _now(), "error": f"pi exited {code}"})
        return code
    # 3) start preview server (detached), write manifest + terminal events
    subprocess.Popen(["bun", "run", "dev", "--", "-H", "0.0.0.0", "-p", str(PREVIEW_PORT)], cwd=SRC)
    os.makedirs("/workspace/out", exist_ok=True)
    json.dump(
        {"artifact_version": 1, "primary_artifact_path": SRC,
         "primary_artifact_type": "landing_page",
         "preview_entry": {"url": "", "port": PREVIEW_PORT, "route": "/"},
         "files": [{"path": f"{SRC}/app/page.tsx", "kind": "source"}], "notes": []},
        open(OUT_MANIFEST, "w", encoding="utf-8"), ensure_ascii=False,
    )
    emit({"type": "preview_ready", "at": _now(), "port": PREVIEW_PORT, "route": "/"})
    emit({"type": "artifact_ready", "at": _now(), "manifest_path": OUT_MANIFEST})
    emit({"type": "builder_finished", "at": _now(), "success": True})
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3b: 写 models.json 生成器**

```python
# backend/onyx/build_runtime/sandbox_image/write_models_json.py
"""Writes ~/.pi/agent/models.json from injected env so Pi uses the GlomiAI
platform model (OpenAI-compatible) inside the sandbox."""
import json
import os
from pathlib import Path

def main() -> None:
    base = os.environ["GLOMI_LLM_BASE_URL"]
    model = os.environ["GLOMI_LLM_MODEL"]
    cfg = {
        "providers": {
            "glomi": {
                "baseUrl": base,
                "api": "openai-completions",
                "apiKey": "GLOMI_LLM_API_KEY",  # env var name; Pi reads it
                "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": False},
                "models": [{"id": model}],
            }
        }
    }
    d = Path.home() / ".pi" / "agent"
    d.mkdir(parents=True, exist_ok=True)
    (d / "models.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
```

- [ ] **Step 3c: 写 Dockerfile**

```dockerfile
# backend/onyx/build_runtime/sandbox_image/Dockerfile
# glomi-landing-page snapshot: Node + bun + Next.js template + Pi + python3.
FROM oven/bun:1-debian AS base
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# Pi coding agent
RUN npm i -g @earendil-works/pi-coding-agent
# launcher scripts
COPY run_build.py write_models_json.py /opt/glomi/
# pre-scaffolded Next.js + Tailwind + shadcn app at /workspace/src
# (reuse the existing opencode template as the seed; copy it in at image-build time)
COPY web-template/ /workspace/src/
WORKDIR /workspace/src
RUN bun install
RUN mkdir -p /workspace/input /workspace/context /workspace/out /workspace/logs
```

> `web-template/` 用现有 `server/features/build/sandbox/image/templates/outputs/web/` 作为种子复制进来(构建镜像时 `cp -r`)。该 snapshot 通过 Daytona snapshot/registry 流程推送(归 INFRA 子项目细化;A 期本地 `docker build` 后用 Daytona 本地 registry)。

- [ ] **Step 4: 跑归一化测试确认通过**

Run: `pytest backend/tests/unit/build_runtime/test_run_build_normalization.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/onyx/build_runtime/sandbox_image/ backend/tests/unit/build_runtime/test_run_build_normalization.py
git commit -m "feat(build_runtime): sandbox image + in-sandbox Pi launcher (normalized event contract)"
```

---

## Task 10: DaytonaSandboxProvider(SDK 实现,mock 测试)

**Files:**
- Create: `backend/onyx/build_runtime/providers/__init__.py`, `providers/sandbox/__init__.py`, `providers/sandbox/daytona_provider.py`
- Test: `backend/tests/unit/build_runtime/test_daytona_provider.py`

**Interfaces:**
- Consumes: `daytona` SDK,`SandboxProvider` Protocol,schemas。
- Produces: `DaytonaSandboxProvider(client=None)`(默认从 `configs` 构造 `Daytona(DaytonaConfig(...))`),实现全部 Protocol 方法。维护 `sandbox_id -> Sandbox` handle 缓存。

- [ ] **Step 1: 写失败测试(mock daytona client)**

```python
# backend/tests/unit/build_runtime/test_daytona_provider.py
from types import SimpleNamespace
from unittest.mock import MagicMock
from onyx.build_runtime.schemas.sandbox import CreateSandboxInput, SandboxFile
from onyx.build_runtime.providers.sandbox.daytona_provider import DaytonaSandboxProvider


def _fake_sandbox():
    sb = SimpleNamespace()
    sb.id = "sbx-1"
    sb.public = False
    sb.fs = MagicMock()
    sb.process = MagicMock()
    sb.process.exec.return_value = SimpleNamespace(exit_code=0, result="ok")
    sb.get_preview_link = MagicMock(return_value=SimpleNamespace(url="http://p", token="t"))
    return sb


def test_create_and_preview_and_delete():
    client = MagicMock()
    sb = _fake_sandbox()
    client.create.return_value = sb
    p = DaytonaSandboxProvider(client=client)

    res = p.create_sandbox(CreateSandboxInput(session_id="s", snapshot="glomi-landing-page"))
    assert res.sandbox_id == "sbx-1"

    p.write_files("sbx-1", [SandboxFile(path="/workspace/a.txt", content="x")])
    sb.fs.upload_file.assert_called_once()

    preview = p.expose_preview("sbx-1", 3000)
    assert preview.url == "http://p" and sb.public is True

    p.delete_sandbox("sbx-1")
    client.delete.assert_called_once_with(sb)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/unit/build_runtime/test_daytona_provider.py -v`
Expected: FAIL(模块缺失)

- [ ] **Step 3: 实现 provider**

```python
# backend/onyx/build_runtime/providers/sandbox/daytona_provider.py
"""SandboxProvider backed by the self-hosted Daytona control plane (daytona SDK).

Daytona is called unmodified via its SDK — AGPL stays confined to Daytona; this
adapter (and GlomiAI) is not a derivative work."""
from typing import Any

from onyx.build_runtime.configs import DAYTONA_API_KEY, DAYTONA_API_URL
from onyx.build_runtime.schemas.sandbox import (
    CommandResult, CreateSandboxInput, CreateSandboxResult, PreviewInfo, SandboxFile,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


class DaytonaSandboxProvider:
    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            from daytona import Daytona, DaytonaConfig

            client = Daytona(DaytonaConfig(api_key=DAYTONA_API_KEY, api_url=DAYTONA_API_URL))
        self.client = client
        self._handles: dict[str, Any] = {}

    def create_sandbox(self, input: CreateSandboxInput) -> CreateSandboxResult:
        from daytona import CreateSandboxFromSnapshotParams

        sandbox = self.client.create(
            CreateSandboxFromSnapshotParams(
                snapshot=input.snapshot,
                env_vars=input.env_vars or None,
                labels=input.labels or None,
            )
        )
        self._handles[sandbox.id] = sandbox
        return CreateSandboxResult(sandbox_id=sandbox.id, status="started")

    def _h(self, sandbox_id: str) -> Any:
        return self._handles[sandbox_id]

    def write_files(self, sandbox_id: str, files: list[SandboxFile]) -> None:
        sb = self._h(sandbox_id)
        for f in files:
            sb.fs.upload_file(f.content.encode("utf-8"), f.path)

    def read_file(self, sandbox_id: str, path: str) -> str:
        data = self._h(sandbox_id).fs.download_file(path)
        return data.decode("utf-8") if isinstance(data, bytes) else str(data)

    def run_command(self, sandbox_id: str, command: str, cwd: str | None = None) -> CommandResult:
        resp = self._h(sandbox_id).process.exec(command, cwd=cwd)
        return CommandResult(exit_code=resp.exit_code, stdout=getattr(resp, "result", "") or "")

    def expose_preview(self, sandbox_id: str, port: int) -> PreviewInfo:
        sb = self._h(sandbox_id)
        sb.public = True
        link = sb.get_preview_link(port)
        return PreviewInfo(url=link.url, port=port, token=getattr(link, "token", None))

    def stop_sandbox(self, sandbox_id: str) -> None:
        self.client.stop(self._h(sandbox_id))

    def delete_sandbox(self, sandbox_id: str) -> None:
        self.client.delete(self._h(sandbox_id))
        self._handles.pop(sandbox_id, None)
```

> 若 spike(Task 1)实测方法名与此不符(如 `stop` 是 `sandbox.stop()`),按实测改这一文件 + 对应 mock。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/unit/build_runtime/test_daytona_provider.py -v`
Expected: PASS(1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/onyx/build_runtime/providers/ backend/tests/unit/build_runtime/test_daytona_provider.py
git commit -m "feat(build_runtime): DaytonaSandboxProvider (SDK-backed, mock-tested)"
```

---

## Task 11: PiBuilderAdapter(launcher 驱动 + 事件 tail,provider-mock 测试)

**Files:**
- Create: `backend/onyx/build_runtime/providers/builder/__init__.py`, `providers/builder/pi_builder_adapter.py`
- Test: `backend/tests/unit/build_runtime/test_pi_adapter.py`

**Interfaces:**
- Consumes: `SandboxProvider`(用其 `run_command` 起 detached launcher、`read_file` tail events),`BuilderAdapter` Protocol,schemas,`parse_builder_event`。
- Produces: `PiBuilderAdapter(provider, poll_interval=1.0, max_polls=...)`。`start_build`:`run_command` 后台跑 `python3 /opt/glomi/run_build.py`(`nohup ... &`)。`subscribe`:循环 `read_file('/workspace/logs/events.jsonl')`,按已读行数增量 yield 新 `BuilderEvent`,遇 `builder_finished`/`builder_failed` 停。`stop`:`run_command` 杀进程。

- [ ] **Step 1: 写失败测试(假 provider,read_file 分两次返回递增内容)**

```python
# backend/tests/unit/build_runtime/test_pi_adapter.py
from onyx.build_runtime.schemas.builder import StartBuildInput
from onyx.build_runtime.providers.builder.pi_builder_adapter import PiBuilderAdapter


class _StubProvider:
    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.commands = []

    def run_command(self, sandbox_id, command, cwd=None):
        self.commands.append(command)
        from onyx.build_runtime.schemas.sandbox import CommandResult
        return CommandResult(exit_code=0, stdout="")

    def read_file(self, sandbox_id, path):
        # advance through snapshots of the events file
        return self._payloads.pop(0) if len(self._payloads) > 1 else self._payloads[0]


def test_subscribe_yields_until_finished():
    line1 = '{"type":"builder_started","at":"0"}\n'
    line2 = line1 + '{"type":"preview_ready","at":"1","port":3000}\n'
    line3 = line2 + '{"type":"builder_finished","at":"2","success":true}\n'
    provider = _StubProvider([line1, line2, line3, line3])
    adapter = PiBuilderAdapter(provider, poll_interval=0)
    start = adapter.start_build(StartBuildInput(build_session_id="b", sandbox_id="sbx"))
    assert any("run_build.py" in c for c in provider.commands)
    types = [e.type for e in adapter.subscribe(start.builder_session_id)]
    assert types[0] == "builder_started"
    assert types[-1] == "builder_finished"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/unit/build_runtime/test_pi_adapter.py -v`
Expected: FAIL(模块缺失)

- [ ] **Step 3: 实现 adapter**

```python
# backend/onyx/build_runtime/providers/builder/pi_builder_adapter.py
"""BuilderAdapter that drives the in-sandbox Pi launcher and tails its
normalized BuilderEvent JSONL. Depends only on our event contract + SandboxProvider."""
import time
from collections.abc import Iterator

from onyx.build_runtime.interfaces.sandbox_provider import SandboxProvider
from onyx.build_runtime.schemas.builder import StartBuildInput, StartBuildResult
from onyx.build_runtime.schemas.events import BuilderEvent, parse_builder_event
from onyx.utils.logger import setup_logger

logger = setup_logger()

_EVENTS_PATH = "/workspace/logs/events.jsonl"
_TERMINAL = {"builder_finished", "builder_failed"}


class PiBuilderAdapter:
    def __init__(self, provider: SandboxProvider, poll_interval: float = 1.0, max_polls: int = 1800):
        self.provider = provider
        self.poll_interval = poll_interval
        self.max_polls = max_polls

    def start_build(self, input: StartBuildInput) -> StartBuildResult:
        # detached launcher; returns immediately
        self.provider.run_command(
            input.sandbox_id,
            "mkdir -p /workspace/logs && nohup python3 /opt/glomi/run_build.py "
            "> /workspace/logs/launcher.log 2>&1 &",
        )
        return StartBuildResult(builder_session_id=input.sandbox_id)

    def subscribe(self, builder_session_id: str) -> Iterator[BuilderEvent]:
        sandbox_id = builder_session_id
        seen = 0
        for _ in range(self.max_polls):
            try:
                content = self.provider.read_file(sandbox_id, _EVENTS_PATH)
            except Exception:
                content = ""
            lines = [ln for ln in content.split("\n") if ln.strip()]
            for raw_line in lines[seen:]:
                event = parse_builder_event(__import__("json").loads(raw_line))
                yield event
                if event.type in _TERMINAL:
                    return
            seen = len(lines)
            if self.poll_interval:
                time.sleep(self.poll_interval)

    def stop(self, builder_session_id: str) -> None:
        self.provider.run_command(builder_session_id, "pkill -f run_build.py || true")
```

> `__import__("json")` 仅为示意避免顶部循环导入冲突;实现时在文件顶部 `import json` 并用 `json.loads`。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/unit/build_runtime/test_pi_adapter.py -v`
Expected: PASS(1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/onyx/build_runtime/providers/builder/ backend/tests/unit/build_runtime/test_pi_adapter.py
git commit -m "feat(build_runtime): PiBuilderAdapter (launcher + event tail)"
```

---

## Task 12: Celery 任务驱动 provisioning + 构建

**Files:**
- Create: `backend/onyx/background/celery/tasks/build_runtime/__init__.py`, `tasks.py`
- Modify: Celery 任务注册处(参考研究:任务模块需被 celery app 导入)
- Modify: `backend/onyx/configs/constants.py`(若 `OnyxCeleryTask` 枚举集中在此,加一个常量名)
- Test: `backend/tests/external_dependency_unit/build_runtime/test_celery_task.py`

**Interfaces:**
- Consumes: `BuildOrchestrator`,`DaytonaSandboxProvider`,`PiBuilderAdapter`,`TemplateService`,`get_session_with_current_tenant`。
- Produces: `@shared_task` `run_build_session_task(self, *, session_id: str, tenant_id: str) -> None`;一个 helper `enqueue_build_session(session_id: UUID, tenant_id: str) -> None`(用 `send_task(..., expires=...)`)。

- [ ] **Step 1: 写失败测试(直接调任务函数体,注入 fakes)**

任务函数把 provider/adapter 的构造抽成可替换 helper,便于测试。测试调用内部 `_run(session_id, db, provider, adapter)`:

```python
# backend/tests/external_dependency_unit/build_runtime/test_celery_task.py
from onyx.db.enums import BuildArtifactType, BuildRuntimeStatus
from onyx.build_runtime.schemas.build_spec import BuildSpec
from onyx.build_runtime.schemas.events import BuilderStarted, BuilderFinished
from onyx.build_runtime.testing.fakes import FakeBuilderAdapter, FakeSandboxProvider
from onyx.db.build_runtime import create_build_runtime_session, get_build_runtime_session
from onyx.background.celery.tasks.build_runtime.tasks import _run


def test_run_drives_orchestrator(db_session):
    s = create_build_runtime_session(
        db_session, user_id=None, artifact_type=BuildArtifactType.LANDING_PAGE,
        template_id="landing_page", spec=BuildSpec(title="t", goal="g"), title="t",
    )
    _run(
        s.id, db_session,
        FakeSandboxProvider(),
        FakeBuilderAdapter([BuilderStarted(at="0"), BuilderFinished(at="1", success=True)]),
    )
    assert get_build_runtime_session(db_session, s.id).status == BuildRuntimeStatus.COMPLETED
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/external_dependency_unit/build_runtime/test_celery_task.py -v`
Expected: FAIL(模块缺失)

- [ ] **Step 3: 实现任务**

```python
# backend/onyx/background/celery/tasks/build_runtime/tasks.py
"""Celery task that drives a build_runtime session end-to-end."""
from uuid import UUID

from celery import Task, shared_task
from sqlalchemy.orm import Session

from onyx.build_runtime.interfaces.builder_adapter import BuilderAdapter
from onyx.build_runtime.interfaces.sandbox_provider import SandboxProvider
from onyx.build_runtime.providers.builder.pi_builder_adapter import PiBuilderAdapter
from onyx.build_runtime.providers.sandbox.daytona_provider import DaytonaSandboxProvider
from onyx.build_runtime.services.build_orchestrator import BuildOrchestrator
from onyx.build_runtime.services.template_service import TemplateService
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.utils.logger import setup_logger

logger = setup_logger()

# 1 hour cap; orchestrator subscribe loop also bounds itself via max_polls.
BUILD_TIME_LIMIT_SECONDS = 3600


def _run(
    session_id: UUID, db_session: Session,
    provider: SandboxProvider, adapter: BuilderAdapter,
) -> None:
    BuildOrchestrator(db_session, provider, adapter, TemplateService()).run(session_id)


@shared_task(
    name="build_runtime.run_build_session",
    soft_time_limit=BUILD_TIME_LIMIT_SECONDS,
    bind=True,
    ignore_result=True,
)
def run_build_session_task(self: Task, *, session_id: str, tenant_id: str) -> None:
    with get_session_with_current_tenant() as db_session:
        provider = DaytonaSandboxProvider()
        adapter = PiBuilderAdapter(provider)
        _run(UUID(session_id), db_session, provider, adapter)
```

```python
# backend/onyx/background/celery/tasks/build_runtime/__init__.py
"""build_runtime celery tasks package. Imported by the celery app so the task
registers (mirror how server/features/build/sandbox/tasks is wired)."""
```

注册:在 celery app 的任务模块清单里加入 `onyx.background.celery.tasks.build_runtime.tasks`(参照 `cleanup_idle_sandboxes_task` 现有注册方式)。enqueue helper(供 API 调用):

```python
# 追加到 tasks.py
from onyx.background.celery.celery_app import celery_app  # 核对真实导入路径

def enqueue_build_session(session_id: UUID, tenant_id: str) -> None:
    celery_app.send_task(
        "build_runtime.run_build_session",
        kwargs={"session_id": str(session_id), "tenant_id": tenant_id},
        expires=BUILD_TIME_LIMIT_SECONDS,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/external_dependency_unit/build_runtime/test_celery_task.py -v`
Expected: PASS(1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/onyx/background/celery/tasks/build_runtime/ backend/tests/external_dependency_unit/build_runtime/test_celery_task.py
git commit -m "feat(build_runtime): celery task driving orchestrator + enqueue helper"
```

---

## Task 13: API 路由 + SSE + 注册 + feature flag

**Files:**
- Create: `backend/onyx/server/features/build_runtime/__init__.py`, `api.py`, `sse.py`
- Modify: `backend/onyx/main.py`(include_router)
- Test: `backend/tests/external_dependency_unit/build_runtime/test_api.py`(TestClient)

**Interfaces:**
- Consumes: `SpecBuilder`,`get_default_llm`,`create_build_runtime_session`,`get_build_runtime_session`,`fetch_build_events_after`,`enqueue_build_session`,`OnyxError`,`ENABLE_BUILD_RUNTIME`,`require_permission`/`current_user`(沿用 build 现有 auth 依赖)。
- Produces:
  - `POST /api/build-runtime/sessions` body `{request: str, artifact_type: str}` → 建 spec + session + enqueue,返回 `{session_id, status}`
  - `GET /api/build-runtime/sessions/{id}` → 会话视图
  - `POST /api/build-runtime/sessions/{id}/terminate`
  - `POST /api/build-runtime/sessions/{id}/instruction` body `{content: str}`(A 期:记录 + 重新 enqueue,占位实现)
  - `GET /api/build-runtime/sessions/{id}/events` → SSE,按 seq 回放 + keepalive

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/external_dependency_unit/build_runtime/test_api.py
import os, pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_BUILD_RUNTIME", "").lower() != "true",
    reason="build_runtime disabled",
)

def test_create_session_returns_id(monkeypatch):
    # stub SpecBuilder + enqueue so no real LLM/celery is needed
    from onyx.server.features.build_runtime import api as mod
    from onyx.build_runtime.schemas.build_spec import BuildSpec
    monkeypatch.setattr(mod, "_build_spec", lambda req, at: BuildSpec(title="t", goal="g"))
    monkeypatch.setattr(mod, "enqueue_build_session", lambda sid, tid: None)

    from onyx.main import app  # app factory
    client = TestClient(app)
    resp = client.post("/api/build-runtime/sessions",
                       json={"request": "做个落地页", "artifact_type": "landing_page"})
    assert resp.status_code == 200
    assert "session_id" in resp.json()
```

> 若直接构造 `TestClient(app)` 触发完整启动开销过大,可改为只挂载本 router 的轻量 `FastAPI()` 实例做路由级测试。二者择一,保证可跑。

- [ ] **Step 2: 跑测试确认失败**

Run: `ENABLE_BUILD_RUNTIME=true pytest backend/tests/external_dependency_unit/build_runtime/test_api.py -v`
Expected: FAIL(模块缺失)

- [ ] **Step 3a: 写 SSE 编码**

```python
# backend/onyx/server/features/build_runtime/sse.py
import json
from onyx.build_runtime.schemas.events import BuilderEvent

SSE_KEEPALIVE = ": keepalive\n\n"

def event_to_sse(seq: int, event: BuilderEvent) -> str:
    data = json.loads(event.model_dump_json())
    data["seq"] = seq
    return f"event: message\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
```

- [ ] **Step 3b: 写路由**

```python
# backend/onyx/server/features/build_runtime/api.py
import time
from collections.abc import Generator
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from onyx.auth.users import current_user
from onyx.background.celery.tasks.build_runtime.tasks import enqueue_build_session
from onyx.build_runtime.configs import ENABLE_BUILD_RUNTIME
from onyx.build_runtime.schemas.build_spec import BuildSpec
from onyx.build_runtime.services.spec_builder import SpecBuilder
from onyx.db.build_runtime import (
    create_build_runtime_session, fetch_build_events_after, get_build_runtime_session,
    update_status,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import BuildArtifactType, BuildRuntimeStatus
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.factory import get_default_llm
from onyx.server.features.build_runtime.sse import SSE_KEEPALIVE, event_to_sse
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter(prefix="/build-runtime", tags=["build-runtime"])


class CreateSessionRequest(BaseModel):
    request: str
    artifact_type: str = "landing_page"


class CreateSessionResponse(BaseModel):
    session_id: str
    status: str


class InstructionRequest(BaseModel):
    content: str


def _guard() -> None:
    if not ENABLE_BUILD_RUNTIME:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "build_runtime disabled")


def _build_spec(request: str, artifact_type: BuildArtifactType) -> BuildSpec:
    return SpecBuilder(get_default_llm()).build(request, artifact_type)


@router.post("/sessions")
def create_session(
    body: CreateSessionRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> CreateSessionResponse:
    _guard()
    artifact_type = BuildArtifactType(body.artifact_type)
    spec = _build_spec(body.request, artifact_type)
    session = create_build_runtime_session(
        db_session, user_id=(user.id if user else None), artifact_type=artifact_type,
        template_id="landing_page", spec=spec, title=spec.title,
    )
    enqueue_build_session(session.id, get_current_tenant_id())
    return CreateSessionResponse(session_id=str(session.id), status=session.status.value)


@router.get("/sessions/{session_id}")
def get_session_view(
    session_id: UUID,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> dict:
    _guard()
    session = get_build_runtime_session(db_session, session_id)
    if session is None:
        raise OnyxError(OnyxErrorCode.BUILD_SESSION_NOT_FOUND, "session not found")
    return {
        "session_id": str(session.id),
        "status": session.status.value,
        "preview_url": session.preview_url,
        "latest_output": session.latest_output,
        "last_error": session.last_error,
    }


@router.post("/sessions/{session_id}/terminate")
def terminate_session(
    session_id: UUID,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> dict:
    _guard()
    update_status(db_session, session_id, BuildRuntimeStatus.TERMINATED)
    return {"ok": True}


@router.post("/sessions/{session_id}/instruction")
def send_instruction(
    session_id: UUID,
    body: InstructionRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> dict:
    _guard()
    # Sub-project A: re-enqueue a rebuild. Full conversational edit lands later.
    enqueue_build_session(session_id, get_current_tenant_id())
    return {"ok": True}


@router.get("/sessions/{session_id}/events")
def stream_events(
    session_id: UUID,
    user: User | None = Depends(current_user),
) -> StreamingResponse:
    _guard()

    def gen() -> Generator[str, None, None]:
        after = 0
        idle = 0
        while idle < 600:  # ~10 min safety bound
            from onyx.db.engine.sql_engine import get_session_with_current_tenant
            with get_session_with_current_tenant() as db:
                rows = fetch_build_events_after(db, session_id, after)
                session = get_build_runtime_session(db, session_id)
            if rows:
                for seq, event in rows:
                    after = seq
                    yield event_to_sse(seq, event)
                idle = 0
            else:
                yield SSE_KEEPALIVE
                idle += 1
            if session and session.status.is_terminal():
                return
            time.sleep(1)

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

> 核对真实 import:`current_user`/`get_session`/`get_current_tenant_id`/`get_session_with_current_tenant` 的确切路径以现有 build feature 里的用法为准(研究里 messages_api/sessions_api 已展示),不一致就改对齐。

- [ ] **Step 3c: 注册路由**

在 `backend/onyx/main.py` 仿 `include_router_with_global_prefix_prepended(application, build_router)` 加:

```python
from onyx.server.features.build_runtime.api import router as build_runtime_router
include_router_with_global_prefix_prepended(application, build_runtime_router)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `ENABLE_BUILD_RUNTIME=true pytest backend/tests/external_dependency_unit/build_runtime/test_api.py -v`
Expected: PASS(1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/onyx/server/features/build_runtime/ backend/onyx/main.py backend/tests/external_dependency_unit/build_runtime/test_api.py
git commit -m "feat(build_runtime): API routes (create/get/terminate/instruction/events SSE) + register"
```

---

## Task 14: 最小前端触发页 + 预览

**Files:**
- Create: `web/src/hooks/useBuildRuntimeSession.ts`
- Create: `web/src/app/build-runtime-dev/page.tsx`
- Test: 手动验证(前端 E2E 留给后续;A 期最小化)

**Interfaces:**
- Consumes: 后端 `POST /api/build-runtime/sessions`、`GET /api/build-runtime/sessions/{id}`。
- Produces: 一个内测页:输入中文需求 → 触发 → 轮询会话 → preview_url 出来后 iframe 展示。

- [ ] **Step 1: 写 SWR hook**

```typescript
// web/src/hooks/useBuildRuntimeSession.ts
import useSWR from "swr";

interface BuildRuntimeSessionView {
  session_id: string;
  status: string;
  preview_url: string | null;
  last_error: Record<string, unknown> | null;
}

export function useBuildRuntimeSession(sessionId: string | null) {
  const { data, error, isLoading } = useSWR<BuildRuntimeSessionView>(
    sessionId ? `/api/build-runtime/sessions/${sessionId}` : null,
    async (url: string) => {
      const res = await fetch(url);
      if (!res.ok) throw new Error("failed to load session");
      return res.json();
    },
    { refreshInterval: 2000 }
  );
  return { session: data, error, isLoading };
}
```

- [ ] **Step 2: 写内测页**

```tsx
// web/src/app/build-runtime-dev/page.tsx
"use client";

import { useState } from "react";
import { useBuildRuntimeSession } from "@/hooks/useBuildRuntimeSession";

export default function BuildRuntimeDevPage() {
  const [request, setRequest] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const { session } = useBuildRuntimeSession(sessionId);

  async function start() {
    const res = await fetch("/api/build-runtime/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request, artifact_type: "landing_page" }),
    });
    const data = await res.json();
    setSessionId(data.session_id);
  }

  return (
    <div className="flex flex-col gap-spacing-interline p-spacing-paragraph">
      <textarea
        className="bg-background-neutral-01 border border-border-02 text-text-01 p-spacing-inline"
        value={request}
        onChange={(e) => setRequest(e.target.value)}
        placeholder="描述你要的落地页"
      />
      <button
        className="bg-background-tint-02 text-text-01 px-spacing-inline py-spacing-inline"
        onClick={start}
      >
        生成
      </button>
      {session && (
        <div className="text-text-02">状态:{session.status}</div>
      )}
      {session?.preview_url && (
        <iframe className="w-full h-[600px] border border-border-02" src={session.preview_url} />
      )}
    </div>
  );
}
```

- [ ] **Step 3: 类型检查 + lint**

Run: `cd web && npm run types:check && npm run lint`
Expected: 通过(若颜色变量名与 `tailwind.config.js` 不符,改成存在的变量)

- [ ] **Step 4: Commit**

```bash
git add web/src/hooks/useBuildRuntimeSession.ts web/src/app/build-runtime-dev/page.tsx
git commit -m "feat(build_runtime): minimal dev trigger page + session polling hook"
```

---

## Task 15: 端到端 gated 测试(真实 Daytona + Pi)

**Files:**
- Create: `backend/tests/external_dependency_unit/build_runtime/test_e2e_landing_page.py`

**Interfaces:**
- Consumes: 真实 `DaytonaSandboxProvider` + `PiBuilderAdapter` + `BuildOrchestrator`,真实 `glomi-landing-page` snapshot(需先按 Task 9 构建并推到 Daytona)。

- [ ] **Step 1: 写 gated e2e**

```python
# backend/tests/external_dependency_unit/build_runtime/test_e2e_landing_page.py
import os
import pytest
import requests

from onyx.db.enums import BuildArtifactType, BuildRuntimeStatus
from onyx.build_runtime.schemas.build_spec import BuildSpec
from onyx.build_runtime.providers.builder.pi_builder_adapter import PiBuilderAdapter
from onyx.build_runtime.providers.sandbox.daytona_provider import DaytonaSandboxProvider
from onyx.build_runtime.services.build_orchestrator import BuildOrchestrator
from onyx.build_runtime.services.template_service import TemplateService
from onyx.db.build_runtime import create_build_runtime_session, get_build_runtime_session

pytestmark = pytest.mark.skipif(
    not os.environ.get("DAYTONA_API_URL"),
    reason="needs a reachable Daytona + glomi-landing-page snapshot",
)


def test_landing_page_end_to_end(db_session):
    spec = BuildSpec(
        title="测试落地页", goal="生成一个含 Hero/CTA 的中文落地页",
        requirements=["Hero 区", "CTA"], acceptance_criteria=["可预览"],
    )
    s = create_build_runtime_session(
        db_session, user_id=None, artifact_type=BuildArtifactType.LANDING_PAGE,
        template_id="landing_page", spec=spec, title=spec.title,
    )
    provider = DaytonaSandboxProvider()
    BuildOrchestrator(db_session, provider, PiBuilderAdapter(provider), TemplateService()).run(s.id)

    session = get_build_runtime_session(db_session, s.id)
    assert session.status == BuildRuntimeStatus.COMPLETED
    assert session.preview_url
    resp = requests.get(session.preview_url, timeout=30)
    assert resp.status_code == 200
```

- [ ] **Step 2: 跑(有 Daytona 时)**

Run: `python -m dotenv -f .vscode/.env run -- pytest backend/tests/external_dependency_unit/build_runtime/test_e2e_landing_page.py -v`
Expected: PASS(无 Daytona env 时 skip)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/external_dependency_unit/build_runtime/test_e2e_landing_page.py
git commit -m "test(build_runtime): gated end-to-end landing page on real Daytona + Pi"
```

---

## Task 16: 收尾 — summary.md + GlomiAI.md + 全量校验

**Files:**
- Modify: `summary.md`(记录子项目 A 落地、坑、学习)
- Modify: `docs/GlomiAI.md`(B 路线表里标注 build_runtime A 节点状态)
- Modify: `docs/superpowers/specs/2026-06-22-build-runtime-roadmap.md`(勾选 A 实现完成)

- [ ] **Step 1: 全量类型检查 + lint + 单测**

Run:
```bash
source .venv/bin/activate
uv run ty check backend/onyx/build_runtime/
uv run pre-commit run --all-files
pytest backend/tests/unit/build_runtime/ -v
```
Expected: 全绿(或仅预期 skip)

- [ ] **Step 2: 更新 summary.md / GlomiAI.md / roadmap**

写明:Daytona+Pi strangler 模块落地;launcher 归一化事件契约是关键解耦点;DB 事件表仿 chat_run_event;AGPL 边界;待 INFRA 提供国内 Daytona。勾选 roadmap 的 A 实现项。

- [ ] **Step 3: Commit**

```bash
git add summary.md docs/GlomiAI.md docs/superpowers/specs/2026-06-22-build-runtime-roadmap.md
git commit -m "docs(build_runtime): record sub-project A completion + learnings"
```

---

## Self-Review(计划 vs spec 覆盖核对)

- 领域模型(BuildSpec/OutputManifest/BuilderEvent/BuildError/sandbox/builder)→ Task 2 ✅
- 新表 + 枚举 + 迁移(BuildRuntimeSession/BuildRuntimeEvent,避开 BuildSessionStatus 命名)→ Task 3 ✅
- DB 操作只放 onyx/db ✅(Task 4);事件表仿 chat_run_event ✅
- SandboxProvider/BuilderAdapter Protocol + fakes → Task 5 ✅
- 错误码 + LLMFlow.BUILD_SPEC_GENERATION + TemplateService + 落地页模板资产 → Task 6 ✅
- BuildOrchestrator 状态机(核心,fake 测试,失败清理)→ Task 7 ✅
- SpecBuilder + 真实 LLM gated 测试(gpt-5-mini)→ Task 8 ✅
- 沙箱镜像 + launcher(Pi→BuilderEvent 归一化,我们自有契约)+ models.json(OpenAI-compatible→Pi openai)→ Task 9 ✅
- DaytonaSandboxProvider(SDK,mock 测试)→ Task 10 ✅
- PiBuilderAdapter(launcher + 事件 tail)→ Task 11 ✅
- Celery @shared_task + expires → Task 12 ✅
- API(create/get/terminate/instruction/events SSE)+ OnyxError + 无 response_model + 注册 + feature flag → Task 13 ✅
- 最小前端触发 + 预览复用 → Task 14 ✅
- 端到端 gated e2e → Task 15 ✅
- summary/GlomiAI/roadmap + 全量校验 → Task 16 ✅

**类型一致性**:`BuildOrchestrator(db, provider, adapter, template_service).run(session_id)`、`SandboxProvider.create_sandbox/write_files/read_file/run_command/expose_preview/stop_sandbox/delete_sandbox`、`BuilderAdapter.start_build/subscribe/stop`、事件 `type` 字面量(builder_started/message_delta/file_changed/preview_ready/artifact_ready/build_blocked/builder_failed/builder_finished)在 Task 2/5/7/9/11 全程一致。

**已知需在执行时与实测对齐**:Daytona SDK 精确方法名(Task 1 spike 校准 → Task 10)、Pi `--mode json` 实际事件字段(Task 9 normalize 内吸收)、若干 onyx 内部 import 路径(current_user/get_session/get_session_with_current_tenant/record_llm_response/celery 注册位置)。这些在对应任务里已标注"按实测/现有用法对齐"。
