# CLI Agent Platform Architecture

## Overview

A platform enabling users to interact with CLI-based AI agents running in isolated containers through a chat interface. Agents can generate artifacts (web apps, PowerPoints, Word docs, markdown, Excel sheets, images) that are viewable and explorable within the UI.

---

## Core Services

### 1. Frontend (Next.js)
- Chat interface for user interaction
- Slide-out panel for VM/filesystem exploration
- Real-time artifact rendering and preview
- Session management UI

### 2. Backend (FastAPI)
- Session lifecycle management
- Artifact tracking and retrieval
- Request proxying to CLI agents
- Streaming response handling
- **Sandbox Manager** (`sandbox_manager.py` - synchronous operations):
  - `provision_sandbox()` - Create and start containers
  - `restore_sandbox()` - Restore from snapshots
  - `terminate_sandbox()` - Stop containers and snapshot
  - All operations are SYNCHRONOUS (no Celery)
- **Background Jobs** (Celery - ONLY for idle timeout):
  - `check_build_sandbox_idle` - Periodic task to terminate idle sandboxes

### 3. PostgreSQL
- Session metadata
- Artifact registry
- Sandbox state tracking
- Organization/user data

---

## Data Models

### Session
```
- id: UUID
- user_id: UUID (nullable - supports anonymous sessions)
- status: enum (active, idle)
- created_at: timestamp
- last_activity_at: timestamp
- sandbox: Sandbox (one-to-one relationship)
- artifacts: list[Artifact] (one-to-many relationship)
- snapshots: list[Snapshot] (one-to-many relationship)
```

### Artifact
```
- id: UUID
- session_id: UUID
- type: enum (web_app, pptx, docx, image, markdown, excel)
- path: string (relative to outputs/)
- name: string
- created_at: timestamp
- updated_at: timestamp
```

### Sandbox
```
- id: UUID
- session_id: UUID (unique - one-to-one with session)
- container_id: string (nullable)
- status: enum (provisioning, running, idle, terminated)
- created_at: timestamp
- last_heartbeat: timestamp (nullable)
```

### Snapshot
```
- id: UUID
- session_id: UUID
- storage_path: string
- created_at: timestamp
- size_bytes: bigint
```

---

## Volume Architecture

Each sandbox container mounts three volumes:

### 1. Knowledge Volume (Read-Only)
- **Source**: Organization's indexed file store
- **Mount**: `/knowledge`
- **Purpose**: Agent can reference org docs, code, data
- **Details**: See persistant-file-store-indexing.md

### 2. Outputs Volume (Read-Write)
- **Source**: Pre-built template OR restored snapshot
- **Mount**: `/outputs`
- **Contents**:
  ```
  /outputs
  ├── web/                    # Next.js skeleton app
  │   ├── package.json
  │   ├── src/
  │   └── ...
  ├── documents/              # Markdown outputs
  ├── presentations/          # .pptx files
  ├── charts/                 # Generated visualizations
  │   └── venv/               # Python environment
  └── manifest.json           # Artifact registry
  ```

### 3. Instructions Volume (Read-Only, Dynamic)
- **Source**: Generated per-session
- **Mount**: `/instructions`
- **Contents**:
  ```
  /instructions
  └── INSTRUCTIONS.md         # Agent system prompt + context
  ```

---

## Sequence Diagram: Standard User Interaction

```
┌──────────┐     ┌──────────┐     ┌─────────────────────────┐     ┌──────────┐
│  User    │     │ Frontend │     │   Backend (FastAPI)     │     │   CLI    │
│ Browser  │     │ (Next.js)│     │   + Sandbox Module      │     │  Agent   │
└────┬─────┘     └────┬─────┘     └───────────┬─────────────┘     └────┬─────┘
     │                │                       │                        │
     │  1. Start Chat │                       │                        │
     │───────────────>│                       │                        │
     │                │                       │                        │
     │                │ 2. POST /sessions     │                        │
     │                │──────────────────────>│                        │
     │                │                       │                        │
     │                │<──────────────────────│ Session Created        │
     │<───────────────│ Show Chat UI          │ (status: initializing) │
     │                │                       │                        │
     │                │                       │ 3. Provision Sandbox   │
     │                │                       │    (async, in background)
     │                │                       │    - Mount knowledge vol
     │                │                       │    - Mount outputs vol │
     │                │                       │    - Mount instructions│
     │                │                       │    - Start container   │
     │                │                       │───────────────────────>│
     │                │                       │                        │
     │  4. Send       │                       │    (provisioning...)   │
     │  "Build me a   │                       │                        │
     │   dashboard"   │                       │                        │
     │───────────────>│                       │                        │
     │                │                       │                        │
     │                │ 5. POST /sessions/{id}/messages                │
     │                │──────────────────────>│                        │
     │                │                       │                        │
     │                │   6. Open SSE Stream  │                        │
     │                │<─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│                        │
     │                │                       │                        │
     │ Show           │  SSE: initializing    │                        │
     │ "Initializing  │<──────────────────────│                        │
     │  sandbox..."   │                       │                        │
     │<───────────────│                       │                        │
     │                │                       │                        │
     │                │                       │<─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┤
     │                │                       │   Sandbox Ready        │
     │                │                       │                        │
     │                │                       │ 7. Proxy to CLI Agent  │
     │                │                       │───────────────────────>│
     │                │                       │                        │
     │                │                       │               8. Agent │
     │                │                       │                Executes│
     │                │                       │                   │    │
     │                │                       │  9. Stream: {"type":"step",
     │                │                       │      "content":"Reading│
     │                │                       │       requirements..."}│
     │                │                       │<───────────────────────│
     │                │                       │                        │
     │                │ SSE: step             │                        │
     │                │<──────────────────────│                        │
     │ Show step      │                       │                        │
     │<───────────────│                       │                        │
     │                │                       │                        │
     │                │                       │  10. Stream: {"type":"step",
     │                │                       │      "content":"Creating
     │                │                       │       components..."}  │
     │                │                       │<───────────────────────│
     │                │ SSE: step             │                        │
     │                │<──────────────────────│                        │
     │ Show step      │                       │                        │
     │<───────────────│                       │                        │
     │                │                       │                        │
     │                │                       │            11. Agent   │
     │                │                       │                writes  │
     │                │                       │                files to│
     │                │                       │            /outputs/web/
     │                │                       │                        │
     │                │                       │  12. Stream: {"type":"artifact",
     │                │                       │      "artifact":{"type":
     │                │                       │       "web_app",...}}
     │                │                       │<───────────────────────│
     │                │                       │                        │
     │                │                       │ 13. Save artifact      │
     │                │                       │     to Postgres        │
     │                │                       │                        │
     │                │ SSE: artifact         │                        │
     │                │<──────────────────────│                        │
     │ Show artifact  │                       │                        │
     │ preview        │                       │                        │
     │<───────────────│                       │                        │
     │                │                       │                        │
     │                │                       │  14. Stream: {"type":"output",
     │                │                       │      "content":"I've built
     │                │                       │       your dashboard..."}
     │                │                       │<───────────────────────│
     │                │ SSE: output           │                        │
     │                │<──────────────────────│                        │
     │ Show response  │                       │                        │
     │<───────────────│                       │                        │
     │                │                       │                        │
     │                │                       │  15. Stream: {"type":"done"}
     │                │                       │<───────────────────────│
     │                │ SSE: done             │                        │
     │                │<──────────────────────│                        │
     │ Enable input   │                       │                        │
     │<───────────────│                       │                        │
     │                │                       │                        │
     │ 16. Click to   │                       │                        │
     │ expand artifact│                       │                        │
     │───────────────>│                       │                        │
     │                │                       │                        │
     │                │ 17. GET /sessions/{id}/artifacts/{id}/content  │
     │                │──────────────────────>│                        │
     │                │                       │                        │
     │                │                       │ 18. Read from sandbox  │
     │                │                       │     filesystem         │
     │                │<──────────────────────│                        │
     │ Render full    │                       │                        │
     │ artifact view  │                       │                        │
     │<───────────────│                       │                        │
     │                │                       │                        │
     ▼                ▼                       ▼                        ▼
```

### Flow Summary

| Step | Action | Description |
|------|--------|-------------|
| 1-3 | **Session Init** | User starts chat → Session created immediately → Sandbox provisions async |
| 4-7 | **Message Send** | User sends prompt → If sandbox not ready, shows "Initializing sandbox..." → Once ready, proxies to CLI agent |
| 8-11 | **Agent Execution** | CLI agent processes request, streams steps, writes files to `/outputs` |
| 12-13 | **Artifact Created** | Agent signals artifact creation → Backend persists metadata |
| 14-15 | **Completion** | Agent sends final response and done signal |
| 16-18 | **Artifact View** | User expands artifact → Backend fetches content from sandbox |

---

## Request Flow

### New Session Flow (Synchronous)
```
1. User creates session via POST /api/build/sessions
2. Backend creates Session record
3. Backend SYNCHRONOUSLY provisions sandbox (sandbox_manager.py):
   a. Creates Sandbox record with status=PROVISIONING
   b. Prepares knowledge volume (bind mount)
   c. Copies outputs template to session-specific volume
   d. Generates instructions file
   e. Starts container with volumes mounted
   f. Updates status=RUNNING with container_id
4. Returns SessionResponse with running sandbox
5. Frontend can now send messages immediately
```

### Follow-up Message Flow (Container Running)
```
1. User sends follow-up message
2. Backend checks Session → Sandbox is running
3. Backend updates last_activity_at timestamp
4. Backend proxies message directly to CLI agent
5. CLI agent streams steps/responses back
6. Backend streams to frontend via SSE
7. Frontend renders chat + any generated artifacts
```

### Follow-up Message Flow (Container Terminated)
```
1. User accesses session via GET /api/build/sessions/{id}
2. Backend checks Session → Sandbox status=TERMINATED
3. Backend SYNCHRONOUSLY restores sandbox (sandbox_manager.py):
   a. Gets latest snapshot from DB
   b. Retrieves snapshot from file store
   c. Extracts to new outputs volume
   d. Starts container with restored state
   e. Updates status=RUNNING with new container_id
4. Returns SessionResponse with running sandbox
5. User can now send messages
```

### Idle Timeout Flow (Celery Background Job - ONLY use of Celery)
```
1. Celery beat schedules check_build_sandbox_idle task (every 5 minutes)
2. Task queries for sandboxes with last_activity_at > 15 minutes ago
3. For each idle sandbox:
   a. Calls terminate_sandbox(session_id, create_snapshot=True)
   b. Snapshot outputs volume to file store
   c. Create Snapshot record (linked to session_id)
   d. Terminate container
   e. Update Sandbox status=TERMINATED
4. Sandbox will be restored on next access
```

---

## API Endpoints

### Sessions
```
POST   /api/build/sessions                    # Create new session       
GET    /api/build/sessions/{id}               # Get session details + wake it up
GET    /api/build/sessions                    # List all sessions (with filters)
DELETE /api/build/sessions/{id}               # End session (full cleanup)
```

### Messages
```
POST   /api/build/sessions/{id}/messages      # Send message (streaming response)
GET    /api/build/sessions/{id}/messages      # Get message history (no pagination)
```

### Artifacts
```
GET    /api/build/sessions/{id}/artifacts             # List artifacts
GET    /api/build/sessions/{id}/artifacts/{artifact_id}  # Get artifact metadata
GET    /api/build/sessions/{id}/artifacts/{artifact_id}/content  # Download/stream content
```

### Filesystem (VM Explorer)
```
POST   /api/build/sessions/{id}/fs/upload             # Upload file to sandbox, to /user-input directory (or similar)
GET    /api/build/sessions/{id}/fs?path=/outputs      # List directory
GET    /api/build/sessions/{id}/fs/read?path=...      # Read file content (maybe clicking on "external files" takes you directly to the source)
```

### Rate Limiting
```
GET   /api/build/limit   # unpaid gets 10 messages total, paid gets paid gets 50 messages / week
```

### Sandbox Manager (Synchronous Internal Functions)
Located in `backend/onyx/server/features/build/sandbox_manager.py`:
```python
# All operations are SYNCHRONOUS - called directly by API endpoints
provision_sandbox(session_id, db_session)            # Provision new sandbox container
restore_sandbox(session_id, db_session)              # Restore sandbox from snapshot
terminate_sandbox(session_id, db_session, create_snapshot)  # Terminate sandbox
```

### Background Jobs (Celery - ONLY for idle timeout)
Located in `backend/onyx/background/celery/tasks/build_sandbox/tasks.py`:
```python
@shared_task
def check_build_sandbox_idle(tenant_id)  # Periodic task to terminate idle sandboxes
```

**IMPORTANT**: Provisioning, restoration, and termination are NOT done via Celery.
They are synchronous operations called directly within API request handlers.

---

## Streaming Protocol

### Pydantic Models (Backend)

```python
from enum import Enum
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field
from datetime import datetime


class StreamingType(Enum):
    """Enum defining all streaming packet types. Single source of truth for type strings."""

    # Control packets
    DONE = "done"
    ERROR = "error"

    # Agent activity packets
    STEP_START = "step_start"
    STEP_DELTA = "step_delta"
    STEP_END = "step_end"

    # Output packets (final response)
    OUTPUT_START = "output_start"
    OUTPUT_DELTA = "output_delta"

    # Artifact packets
    ARTIFACT_CREATED = "artifact_created"
    ARTIFACT_UPDATED = "artifact_updated"

    # Tool usage packets
    TOOL_START = "tool_start"
    TOOL_OUTPUT = "tool_output"
    TOOL_END = "tool_end"

    # File operation packets
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"


class BasePacket(BaseModel):
    """Base class for all streaming packets."""
    type: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


################################################
# Control Packets
################################################
class DonePacket(BasePacket):
    """Signals completion of the agent's response."""
    type: Literal["done"] = StreamingType.DONE.value
    summary: str | None = None


class ErrorPacket(BasePacket):
    """Signals an error occurred during processing."""
    type: Literal["error"] = StreamingType.ERROR.value
    message: str
    code: str | None = None  # e.g., "TIMEOUT", "SANDBOX_ERROR", "LLM_ERROR"
    recoverable: bool = False


################################################
# Agent Step Packets (thinking/progress)
################################################
class StepStart(BasePacket):
    """Signals the start of a new agent step/action."""
    type: Literal["step_start"] = StreamingType.STEP_START.value
    step_id: str  # Unique identifier for this step
    title: str | None = None  # e.g., "Reading requirements", "Creating components"


class StepDelta(BasePacket):
    """Streaming content for an agent step."""
    type: Literal["step_delta"] = StreamingType.STEP_DELTA.value
    step_id: str
    content: str  # Incremental text content


class StepEnd(BasePacket):
    """Signals completion of an agent step."""
    type: Literal["step_end"] = StreamingType.STEP_END.value
    step_id: str
    status: Literal["success", "failed", "skipped"] = "success"


################################################
# Output Packets (final agent response)
################################################
class OutputStart(BasePacket):
    """Signals the start of the agent's final output."""
    type: Literal["output_start"] = StreamingType.OUTPUT_START.value


class OutputDelta(BasePacket):
    """Streaming content for the agent's final output."""
    type: Literal["output_delta"] = StreamingType.OUTPUT_DELTA.value
    content: str  # Incremental text content


################################################
# Artifact Packets
################################################
class ArtifactType(str, Enum):
    WEB_APP = "web_app"
    PPTX = "pptx"
    DOCX = "docx"
    IMAGE = "image"
    MARKDOWN = "markdown"
    EXCEL = "excel"


class ArtifactMetadata(BaseModel):
    """Metadata for an artifact."""
    id: str  # UUID
    type: ArtifactType
    name: str
    path: str  # Relative path within /outputs
    preview_url: str | None = None  # URL for inline preview if available


class ArtifactCreated(BasePacket):
    """Signals a new artifact has been created."""
    type: Literal["artifact_created"] = StreamingType.ARTIFACT_CREATED.value
    artifact: ArtifactMetadata


class ArtifactUpdated(BasePacket):
    """Signals an existing artifact has been updated."""
    type: Literal["artifact_updated"] = StreamingType.ARTIFACT_UPDATED.value
    artifact: ArtifactMetadata
    changes: list[str] | None = None  # Description of what changed


################################################
# Tool Usage Packets
################################################
class ToolStart(BasePacket):
    """Signals the agent is invoking a tool."""
    type: Literal["tool_start"] = StreamingType.TOOL_START.value
    tool_name: str  # e.g., "bash", "read_file", "write_file", "web_search"
    tool_input: dict | str | None = None  # Input parameters


class ToolOutput(BasePacket):
    """Output from a tool invocation."""
    type: Literal["tool_output"] = StreamingType.TOOL_OUTPUT.value
    tool_name: str
    output: str | None = None
    is_error: bool = False


class ToolEnd(BasePacket):
    """Signals completion of a tool invocation."""
    type: Literal["tool_end"] = StreamingType.TOOL_END.value
    tool_name: str
    status: Literal["success", "failed"] = "success"


################################################
# File Operation Packets
################################################
class FileWrite(BasePacket):
    """Signals a file was written to the outputs volume."""
    type: Literal["file_write"] = StreamingType.FILE_WRITE.value
    path: str  # Relative path within /outputs
    size_bytes: int | None = None


class FileDelete(BasePacket):
    """Signals a file was deleted from the outputs volume."""
    type: Literal["file_delete"] = StreamingType.FILE_DELETE.value
    path: str


################################################
# Packet Union
################################################
# Discriminated union of all possible packet types
PacketObj = Union[
    # Control packets
    DonePacket,
    ErrorPacket,
    # Step packets
    StepStart,
    StepDelta,
    StepEnd,
    # Output packets
    OutputStart,
    OutputDelta,
    # Artifact packets
    ArtifactCreated,
    ArtifactUpdated,
    # Tool packets
    ToolStart,
    ToolOutput,
    ToolEnd,
    # File packets
    FileWrite,
    FileDelete,
]


class StreamPacket(BaseModel):
    """Wrapper for streaming packets with session context."""
    session_id: str
    obj: Annotated[PacketObj, Field(discriminator="type")]
```

### SSE Event Format (Backend → Frontend)

Each packet is sent as an SSE event with the packet JSON as data:

```
event: message
data: {"type": "step_start", "step_id": "abc123", "title": "Reading requirements", "timestamp": "2024-01-15T10:30:00Z"}

event: message
data: {"type": "step_delta", "step_id": "abc123", "content": "Analyzing the file structure...", "timestamp": "2024-01-15T10:30:01Z"}

event: message
data: {"type": "tool_start", "tool_name": "write_file", "tool_input": {"path": "/outputs/web/src/App.tsx"}, "timestamp": "2024-01-15T10:30:02Z"}

event: message
data: {"type": "file_write", "path": "web/src/App.tsx", "size_bytes": 1523, "timestamp": "2024-01-15T10:30:03Z"}

event: message
data: {"type": "artifact_created", "artifact": {"id": "uuid-here", "type": "web_app", "name": "Dashboard", "path": "web/"}, "timestamp": "2024-01-15T10:30:04Z"}

event: message
data: {"type": "output_start", "timestamp": "2024-01-15T10:30:05Z"}

event: message
data: {"type": "output_delta", "content": "I've built your dashboard with the following features...", "timestamp": "2024-01-15T10:30:05Z"}

event: message
data: {"type": "done", "summary": "Created a Next.js dashboard with 3 components", "timestamp": "2024-01-15T10:30:10Z"}
```

### TypeScript Types (Frontend)

```typescript
// Enum for packet types
enum StreamingType {
  DONE = "done",
  ERROR = "error",
  STEP_START = "step_start",
  STEP_DELTA = "step_delta",
  STEP_END = "step_end",
  OUTPUT_START = "output_start",
  OUTPUT_DELTA = "output_delta",
  ARTIFACT_CREATED = "artifact_created",
  ARTIFACT_UPDATED = "artifact_updated",
  TOOL_START = "tool_start",
  TOOL_OUTPUT = "tool_output",
  TOOL_END = "tool_end",
  FILE_WRITE = "file_write",
  FILE_DELETE = "file_delete",
}

// Artifact types
type ArtifactType = "web_app" | "pptx" | "docx" | "image" | "markdown" | "excel";

interface ArtifactMetadata {
  id: string;
  type: ArtifactType;
  name: string;
  path: string;
  preview_url?: string;
}

// Base packet interface
interface BasePacket {
  type: string;
  timestamp: string;
}

// Control packets
interface DonePacket extends BasePacket {
  type: "done";
  summary?: string;
}

interface ErrorPacket extends BasePacket {
  type: "error";
  message: string;
  code?: string;
  recoverable: boolean;
}

// Step packets
interface StepStart extends BasePacket {
  type: "step_start";
  step_id: string;
  title?: string;
}

interface StepDelta extends BasePacket {
  type: "step_delta";
  step_id: string;
  content: string;
}

interface StepEnd extends BasePacket {
  type: "step_end";
  step_id: string;
  status: "success" | "failed" | "skipped";
}

// Output packets
interface OutputStart extends BasePacket {
  type: "output_start";
}

interface OutputDelta extends BasePacket {
  type: "output_delta";
  content: string;
}

// Artifact packets
interface ArtifactCreated extends BasePacket {
  type: "artifact_created";
  artifact: ArtifactMetadata;
}

interface ArtifactUpdated extends BasePacket {
  type: "artifact_updated";
  artifact: ArtifactMetadata;
  changes?: string[];
}

// Tool packets
interface ToolStart extends BasePacket {
  type: "tool_start";
  tool_name: string;
  tool_input?: Record<string, unknown> | string;
}

interface ToolOutput extends BasePacket {
  type: "tool_output";
  tool_name: string;
  output?: string;
  is_error: boolean;
}

interface ToolEnd extends BasePacket {
  type: "tool_end";
  tool_name: string;
  status: "success" | "failed";
}

// File packets
interface FileWrite extends BasePacket {
  type: "file_write";
  path: string;
  size_bytes?: number;
}

interface FileDelete extends BasePacket {
  type: "file_delete";
  path: string;
}

// Discriminated union
type StreamPacket =
  | DonePacket
  | ErrorPacket
  | StepStart
  | StepDelta
  | StepEnd
  | OutputStart
  | OutputDelta
  | ArtifactCreated
  | ArtifactUpdated
  | ToolStart
  | ToolOutput
  | ToolEnd
  | FileWrite
  | FileDelete;
```

---

## Frontend Components

### Chat Panel
- Message input
- Message history with agent steps
- Artifact inline previews

### VM Explorer (Slide-out)
- File tree navigation
- File content viewer
- Artifact-specific renderers:
  - Next.js: iframe preview + code view
  - PPTX: slide viewer
  - Markdown: rendered preview
  - Charts: image/interactive view

---

## Configuration

```yaml
sandbox:
  idle_timeout_seconds: 900          # 15 minutes
  max_concurrent_per_org: 10
  container_image: "cli-agent:latest"
  resource_limits:
    memory: "2Gi"
    cpu: "1"
  
storage:
  snapshots_bucket: "sandbox-snapshots"
  outputs_template_path: "/templates/outputs"
  
knowledge:
  base_path: "/mnt/knowledge"
```

---

## Open Questions

1. **Container orchestration**: Docker directly? Kubernetes? Firecracker?
2. **CLI agent protocol**: How does it receive messages? stdin? HTTP? Socket?
3. **Artifact detection**: How do we know when an artifact is created/updated? Filesystem watching? Agent reports it?
4. **Knowledge volume**: Per-org? Per-user? How large can it get?
5. **Snapshot storage**: S3? Local NFS? How long to retain?
6. **Multi-turn context**: Does the CLI agent maintain conversation history, or do we replay?
7. **Security**: Network isolation? What can the agent access?
8. **Preview generation**: Who renders Next.js apps? Dev server in container? Separate preview service?

---

## Next Steps

- [ ] Define CLI agent interface contract
- [ ] Design container image contents
- [ ] Detail snapshot/restore mechanics
- [ ] Specify frontend state management
- [ ] Define artifact type handlers
- [ ] Security model and isolation
- [ ] Monitoring and observability