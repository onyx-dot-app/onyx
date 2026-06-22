对，你说得对。  
**我上一版接口草案用了 TypeScript 风格来表达结构，但如果你的后端主栈是 Python，那下一步应该直接收敛成 Python 版本。**

你可以把上一版理解成“领域模型草图”，**不是语言定稿**。  
下面我直接给你改成一版更适合 **Python 后端 / FastAPI / Pydantic / SQLAlchemy 风格** 的版本。

---

# Python 版接口设计建议

我建议你在 Python 里分三层来写：

1. **Schema / Domain Models**：Pydantic
2. **Abstract Interfaces**：`Protocol` 或 `ABC`
3. **Concrete Implementations**：`DaytonaSandboxProvider`、`PiBuilderAdapter`

---

# 1. BuildSession 领域模型

如果你是 FastAPI，我建议：
- **对外 API / 内部编排输入输出**：Pydantic
- **数据库 ORM**：SQLAlchemy 单独一套
- 不要 ORM 和 API model 混写

## 1.1 枚举定义

```python
from enum import Enum


class BuildArtifactType(str, Enum):
    LANDING_PAGE = "landing_page"
    SLIDES = "slides"
    REPORT = "report"
    DASHBOARD = "dashboard"
    TOOL = "tool"


class BuildSessionStatus(str, Enum):
    QUEUED = "queued"
    SPEC_READY = "spec_ready"
    PROVISIONING = "provisioning"
    SANDBOX_READY = "sandbox_ready"
    BUILDER_STARTING = "builder_starting"
    BUILDING = "building"
    PREVIEW_READY = "preview_ready"
    AWAITING_FEEDBACK = "awaiting_feedback"
    REBUILDING = "rebuilding"
    REVIEWING = "reviewing"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"
    TERMINATED = "terminated"


class SandboxProviderType(str, Enum):
    DAYTONA = "daytona"


class BuilderType(str, Enum):
    PI = "pi"
```

---

## 1.2 BuildSpec

```python
from pydantic import BaseModel, Field
from typing import Optional, List


class BuildSpecInputs(BaseModel):
    uploaded_files: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    external_urls: List[str] = Field(default_factory=list)


class BuildSpecOutputs(BaseModel):
    primary_format: str
    extra_formats: List[str] = Field(default_factory=list)


class BuildSpec(BaseModel):
    title: str
    goal: str

    target_audience: Optional[str] = None
    scenario: Optional[str] = None

    requirements: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    brand_rules: List[str] = Field(default_factory=list)
    visual_style: List[str] = Field(default_factory=list)

    inputs: BuildSpecInputs = Field(default_factory=BuildSpecInputs)
    outputs: BuildSpecOutputs
    acceptance_criteria: List[str] = Field(default_factory=list)
```

---

## 1.3 输出、审查、错误模型

```python
from typing import Dict, Any


class PreviewEntry(BaseModel):
    url: str
    port: int
    route: Optional[str] = None


class OutputFile(BaseModel):
    path: str
    kind: str  # source / preview / export / asset / log
    size_bytes: Optional[int] = None


class OutputManifest(BaseModel):
    artifact_version: int = 1
    primary_artifact_path: str
    primary_artifact_type: str
    preview_entry: Optional[PreviewEntry] = None
    files: List[OutputFile] = Field(default_factory=list)
    screenshots: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class ReviewIssue(BaseModel):
    code: str
    severity: str  # low / medium / high
    message: str
    suggested_fix: Optional[str] = None


class CriteriaCheck(BaseModel):
    criterion: str
    passed: bool
    note: Optional[str] = None


class ReviewResult(BaseModel):
    passed: bool
    score: Optional[float] = None
    strengths: List[str] = Field(default_factory=list)
    issues: List[ReviewIssue] = Field(default_factory=list)
    criteria_check: List[CriteriaCheck] = Field(default_factory=list)
    next_action: str  # publish / rebuild / ask_user


class BuildError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: str
```

---

## 1.4 BuildSession

```python
from pydantic import BaseModel
from typing import Optional


class BuildSession(BaseModel):
    id: str

    parent_chat_session_id: str
    parent_message_id: Optional[str] = None

    user_id: str
    org_id: Optional[str] = None

    artifact_type: BuildArtifactType
    template_id: str
    template_version: str

    title: str
    summary: Optional[str] = None

    status: BuildSessionStatus
    status_reason: Optional[str] = None

    spec: BuildSpec
    evidence_pack_ref: Optional[str] = None

    sandbox_provider: SandboxProviderType = SandboxProviderType.DAYTONA
    sandbox_id: Optional[str] = None
    sandbox_snapshot_id: Optional[str] = None
    sandbox_region: Optional[str] = None

    builder_type: BuilderType = BuilderType.PI
    builder_session_id: Optional[str] = None
    builder_run_id: Optional[str] = None

    preview_url: Optional[str] = None
    preview_port: Optional[int] = None

    workspace_volume_ref: Optional[str] = None
    evidence_volume_ref: Optional[str] = None
    assets_volume_ref: Optional[str] = None

    latest_output: Optional[OutputManifest] = None
    latest_review: Optional[ReviewResult] = None

    retry_count: int = 0
    last_error: Optional[BuildError] = None

    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    archived_at: Optional[str] = None
    terminated_at: Optional[str] = None
```

---

# 2. SandboxProvider 抽象接口

Python 里我更建议用 **`Protocol`**。  
原因是你后面做 mock、测试、替换实现更轻。

## 2.1 公共模型

```python
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field


class VolumeMount(BaseModel):
    volume_ref: str
    mount_path: str
    subpath: Optional[str] = None
    read_only: bool = False


class SandboxFile(BaseModel):
    path: str
    content: str | bytes
    encoding: str = "utf8"  # utf8 / base64 / binary


class SandboxCommand(BaseModel):
    command: str
    cwd: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict)
    timeout_seconds: Optional[int] = None


class CreateSandboxInput(BaseModel):
    session_id: str
    snapshot_id: str
    artifact_type: BuildArtifactType

    mounts: List[VolumeMount] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)

    auto_stop_minutes: Optional[int] = None
    auto_archive_hours: Optional[int] = None
    ephemeral: bool = False


class CreateSandboxResult(BaseModel):
    sandbox_id: str
    region: Optional[str] = None
    status: str  # creating / started


class CommandResult(BaseModel):
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: Optional[int] = None


class PreviewInfo(BaseModel):
    url: str
    port: int
    route: Optional[str] = None


class SandboxStatusInfo(BaseModel):
    sandbox_id: str
    state: str
    last_updated_at: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

---

## 2.2 Protocol 定义

```python
from typing import Protocol, Callable, Awaitable


class SandboxProvider(Protocol):
    async def create_sandbox(self, input: CreateSandboxInput) -> CreateSandboxResult:
        ...

    async def get_sandbox_status(self, sandbox_id: str) -> SandboxStatusInfo:
        ...

    async def write_files(self, sandbox_id: str, files: list[SandboxFile]) -> None:
        ...

    async def read_files(self, sandbox_id: str, paths: list[str]) -> list[SandboxFile]:
        ...

    async def run_command(self, sandbox_id: str, command: SandboxCommand) -> CommandResult:
        ...

    async def stream_logs(
        self,
        sandbox_id: str,
        on_event: Callable[[str], Awaitable[None]]
    ) -> Callable[[], Awaitable[None]]:
        ...

    async def expose_preview(self, sandbox_id: str, port: int) -> PreviewInfo:
        ...

    async def stop_sandbox(self, sandbox_id: str) -> None:
        ...

    async def resume_sandbox(self, sandbox_id: str) -> None:
        ...

    async def archive_sandbox(self, sandbox_id: str) -> None:
        ...

    async def delete_sandbox(self, sandbox_id: str) -> None:
        ...
```

---

# 3. BuilderAdapter 抽象接口

这层就是给 Pi 用的。

## 3.1 事件模型

```python
from typing import Literal, Union


class BuilderStartedEvent(BaseModel):
    type: Literal["builder_started"]
    at: str


class MessageDeltaEvent(BaseModel):
    type: Literal["message_delta"]
    at: str
    text: str


class ToolCallStartedEvent(BaseModel):
    type: Literal["tool_call_started"]
    at: str
    tool: str
    input_summary: Optional[str] = None


class ToolCallFinishedEvent(BaseModel):
    type: Literal["tool_call_finished"]
    at: str
    tool: str
    success: bool


class FileChangedEvent(BaseModel):
    type: Literal["file_changed"]
    at: str
    path: str


class PreviewReadyEvent(BaseModel):
    type: Literal["preview_ready"]
    at: str
    port: int
    route: Optional[str] = None


class ArtifactReadyEvent(BaseModel):
    type: Literal["artifact_ready"]
    at: str
    manifest_path: str


class BuildBlockedEvent(BaseModel):
    type: Literal["build_blocked"]
    at: str
    reason: str


class BuilderFailedEvent(BaseModel):
    type: Literal["builder_failed"]
    at: str
    error: str


class BuilderFinishedEvent(BaseModel):
    type: Literal["builder_finished"]
    at: str
    success: bool


BuilderEvent = Union[
    BuilderStartedEvent,
    MessageDeltaEvent,
    ToolCallStartedEvent,
    ToolCallFinishedEvent,
    FileChangedEvent,
    PreviewReadyEvent,
    ArtifactReadyEvent,
    BuildBlockedEvent,
    BuilderFailedEvent,
    BuilderFinishedEvent,
]
```

---

## 3.2 启动参数

```python
class BuilderConfig(BaseModel):
    model: Optional[str] = None
    max_turns: Optional[int] = None
    timeout_seconds: Optional[int] = None


class StartBuildInput(BaseModel):
    build_session_id: str
    sandbox_id: str

    workspace_path: str
    task_file_path: str
    evidence_path: Optional[str] = None

    mode: str  # initial_build / rebuild
    instruction: str

    builder_config: BuilderConfig = Field(default_factory=BuilderConfig)


class StartBuildResult(BaseModel):
    builder_session_id: str
    builder_run_id: Optional[str] = None
```

---

## 3.3 Protocol 定义

```python
class BuilderAdapter(Protocol):
    async def start_build(self, input: StartBuildInput) -> StartBuildResult:
        ...

    async def send_instruction(self, builder_session_id: str, message: str) -> None:
        ...

    async def subscribe(
        self,
        builder_session_id: str,
        on_event: Callable[[BuilderEvent], Awaitable[None]]
    ) -> Callable[[], Awaitable[None]]:
        ...

    async def stop(self, builder_session_id: str) -> None:
        ...
```

---

# 4. Service 层建议

你是 Python 后端的话，真正落地通常不是直接调 Protocol，而是套一层 service。

---

## 4.1 BuildSessionService

```python
class BuildSessionService(Protocol):
    async def create(
        self,
        *,
        parent_chat_session_id: str,
        user_id: str,
        artifact_type: BuildArtifactType,
        template_id: str,
        spec: BuildSpec,
    ) -> BuildSession:
        ...

    async def get(self, session_id: str) -> BuildSession:
        ...

    async def update_status(
        self,
        session_id: str,
        status: BuildSessionStatus,
        reason: Optional[str] = None,
    ) -> None:
        ...

    async def attach_sandbox(
        self,
        session_id: str,
        *,
        sandbox_id: str,
        snapshot_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> None:
        ...

    async def attach_builder(
        self,
        session_id: str,
        *,
        builder_session_id: str,
        builder_run_id: Optional[str] = None,
    ) -> None:
        ...

    async def set_preview(self, session_id: str, preview: PreviewInfo) -> None:
        ...

    async def set_output(self, session_id: str, output: OutputManifest) -> None:
        ...

    async def set_review(self, session_id: str, review: ReviewResult) -> None:
        ...

    async def fail(self, session_id: str, error: BuildError) -> None:
        ...

    async def archive(self, session_id: str) -> None:
        ...

    async def terminate(self, session_id: str) -> None:
        ...
```

---

## 4.2 BuildOrchestrator

这个类才是你主控交付模式真正的中枢。

```python
class BuildOrchestrator:
    def __init__(
        self,
        build_session_service: BuildSessionService,
        sandbox_provider: SandboxProvider,
        builder_adapter: BuilderAdapter,
    ) -> None:
        self.build_session_service = build_session_service
        self.sandbox_provider = sandbox_provider
        self.builder_adapter = builder_adapter

    async def create_and_start_build(self, spec: BuildSpec, artifact_type: BuildArtifactType) -> BuildSession:
        ...
```

### 它主要做 6 件事
1. 创建 `BuildSession`
2. 选择 template / snapshot
3. 创建 Daytona sandbox
4. 写入 `task.json / AGENTS.md / SYSTEM.md`
5. 启动 Pi builder
6. 消费 builder event 并回写 session 状态

---

# 5. FastAPI 层建议

如果你是 Python 后端，API 层建议保持很薄。

例如：

```python
from fastapi import APIRouter

router = APIRouter(prefix="/api/build", tags=["build"])
```

你可以先做 4 个核心接口：

### 创建 BuildSession
`POST /api/build/sessions`

### 查询 BuildSession
`GET /api/build/sessions/{session_id}`

### 继续修改
`POST /api/build/sessions/{session_id}/instruction`

### 终止任务
`POST /api/build/sessions/{session_id}/terminate`

这样主控层和前端画布都能挂上去。

---

# 6. Python 项目结构建议

你前面那份架构如果用 Python 落地，我建议这样切：

```text
backend/glomi/build_runtime/
  schemas/
    build_session.py
    build_spec.py
    output_manifest.py
    review_result.py
    sandbox.py
    builder.py

  interfaces/
    sandbox_provider.py
    builder_adapter.py
    build_session_service.py

  services/
    build_orchestrator.py
    review_service.py
    template_service.py

  providers/
    sandbox/
      daytona_provider.py
    builder/
      pi_builder_adapter.py

  repositories/
    build_session_repo.py

  api/
    routes.py
```

---

# 7. 一个很小但很关键的建议

如果你是 Python 后端，**不要为了 Pi 是 Node 生态就把整个编排层改成 TS**。  
正确方式应该是：

- **Python**：主控、编排、状态机、API、持久化
- **Daytona**：runtime
- **Pi**：builder 进程，通过 RPC/JSON 流与 Python 通信

这样最稳。

因为 Pi 官方本来就支持 RPC，适合跨语言集成；而 SDK 更适合同 Node 同进程深度集成。[Source](https://pi.dev/docs/latest/sdk)

---

# 8. 我帮你纠正一句话总结

上一版不是“写错了”，而是**写成了语言无关的接口草图偏 TS 表达**。  
如果你现在要进入工程设计阶段，那就应该正式切成：

> **Pydantic 定义领域模型，Protocol 定义接口，Service 负责编排，Provider 负责 Daytona/Pi 具体实现。**

这才是 Python 后端最自然的落法。

---
