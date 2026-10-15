<h2 align="center">
    <a href="https://www.onyx.app/?utm_source=onyx_repo&utm_medium=github&utm_campaign=readme"> <img width="50%" src="https://github.com/onyx-dot-app/onyx/blob/logo/OnyxLogoCropped.jpg?raw=true" /></a>
</h2>

<h1 align="center">Onyx Craft</h1>

<p align="center">
  <strong>Build apps, documents, and presentations from your company knowledge</strong>
</p>

<p align="center">
  <a href="https://docs.onyx.app/overview/core_features/craft"><img alt="Documentation" src="https://img.shields.io/badge/docs-onyx.app-blue?style=flat-square" /></a>
  <a href="https://github.com/onyx-dot-app/onyx/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green?style=flat-square" /></a>
    <a href="https://discord.gg/TDJ59cGV2X" target="_blank" rel="noopener noreferrer">
        <img src="https://img.shields.io/badge/discord-join-blue.svg?logo=discord&logoColor=white" alt="Discord" />
    </a>
  <img alt="GitHub Repo stars" src="https://img.shields.io/github/stars/onyx-dot-app/onyx" />
</p>

---

<p align="center">
  <a href="https://www.youtube.com/watch?v=Hvjn76YSIRY">
    <img src="https://img.youtube.com/vi/Hvjn76YSIRY/hqdefault.jpg" alt="Watch the video" />
  </a>
</p>

---

## Overview

Onyx Craft is an AI coding agent that creates web applications, documents, presentations, and more using your company's indexed knowledge. Users describe what they want in natural language, and the agent builds artifacts in an isolated sandbox environment with access to documents from connected sources like Linear, Slack, Google Drive, Confluence, and more.

For detailed documentation, visit [our docs](https://docs.onyx.app/overview/core_features/craft).

## Key Features

- **Web Applications** — Build Next.js applications with React, shadcn/ui, and Recharts for interactive dashboards and tools
- **Documents & Reports** — Generate polished markdown documents with DOCX export
- **Knowledge Integration** — Access indexed documents from your connectors (Linear, Slack, Google Drive, Confluence, etc.)
- **Real-time Preview** — Watch the agent build with live output streaming and tool call visibility
- **Session Management** — Pre-provisioned sandboxes, automatic snapshots, and session restore

## Quick Start

### Requirements

- Onyx deployment with an LLM provider configured (Anthropic, OpenAI, etc.)
- Kubernetes sandbox infrastructure with Kata Firecracker enabled. The Craft
  docker-compose sandbox backend has been removed.

### New Installations

Deploy Onyx Craft with the Kubernetes deployment path. For local development,
use [docs/craft/dev/local-kubernetes.md](/docs/craft/dev/local-kubernetes.md)
for the one-shot setup via `make craft-up`.

The docker-compose quickstart does not install Craft. It still runs the rest of
Onyx, but it does not provision Craft sandboxes.

### Existing Deployments

Migrate existing Craft deployments to the Kubernetes path before enabling Craft
on the new release. The deprecated `--include-craft` docker-compose flag is
rejected by the installer, and the old `docker-compose.craft.yml` overlay is no
longer shipped.

## How It Works

1. **User visits `/craft/v1`** — A sandbox is pre-provisioned in the background
2. **User describes what they want** — Message is sent to the OpenCode agent
3. **Agent builds artifacts** — Uses company knowledge and uploaded files
4. **Live preview shows output** — Next.js app, markdown, or other artifacts
5. **User iterates or downloads** — Request changes or export finished work

## Technical Architecture

### Sandbox Runtime

- Kata Firecracker VM isolation through Kubernetes `RuntimeClass`
- ClusterIP services for sandbox traffic
- S3-based snapshots for session persistence
- Automatic cleanup of idle sandboxes (default: 1 hour timeout)
- One main sandbox container that runs opencode and the Next.js preview server
- A firewall init container that prepares the network boundary before the main
  container starts

For local development, see [docs/craft/dev/local-kubernetes.md](/docs/craft/dev/local-kubernetes.md) — one-shot setup via `make craft-up`.

### Session Lifecycle

Sessions go through these states:

| State            | Description                                                     |
| ---------------- | --------------------------------------------------------------- |
| **Provisioning** | Sandbox being created when user visits /craft                   |
| **Ready**        | Sandbox ready, waiting for first message                        |
| **Running**      | Active session with agent processing                            |
| **Idle**         | No recent activity                                              |
| **Sleeping**     | Idle timeout reached, pod terminated (K8s only), snapshot saved |
| **Restored**     | User returns, snapshot loaded, session continues                |

### Sandbox Workspace Structure

Each session gets an isolated workspace:

```
$SANDBOX_ROOT/
├── files/                     # Symlink to user's knowledge files
└── sessions/
    └── {session_id}/
        ├── outputs/web/       # Next.js application
        ├── .venv/             # Python environment
        ├── .opencode/skills/  # Agent skills
        ├── attachments/       # User uploads
        ├── AGENTS.md          # Agent instructions
        └── opencode.json      # LLM configuration
```

### Sandbox Cleanup

Idle sandboxes are cleaned up by a Celery background task:

- **Trigger**: Sandbox idle longer than `SANDBOX_IDLE_TIMEOUT_SECONDS` (default: 1 hour)
- Creates snapshots of all sessions, terminates the pod, marks sandbox as "sleeping"

## Configuration

Key configuration categories (see source for full reference):

- **Core** — `ENABLE_CRAFT`
- **Lifecycle** — Idle timeout (default 1 hour)
- **Kubernetes** — Namespace, sandbox image, RuntimeClass, S3 bucket for snapshots
- **File uploads** — Size limits (50MB per file, 20 files per session, 200MB total)
- **Rate limits** — Free users: 5 messages total; Paid users: 25 messages/week

## Tech Stack

**Frontend**

- Next.js, React, TypeScript
- Zustand for state management
- shadcn/ui components

**Backend**

- FastAPI, SQLAlchemy, Celery
- PostgreSQL for session/sandbox metadata
- S3-compatible storage for snapshots

**Agent**

- opencode-serve (HTTP transport)
- JSON-RPC 2.0 over stdin/stdout

**Sandbox Environment**

- Next.js 16, React 19
- shadcn/ui, Tailwind CSS, Recharts
- Python 3.11 with numpy, pandas, matplotlib

## Coming Soon

- **Presentations** — Create slide decks with AI-generated visuals using nanobanana
- **Spreadsheets**
- **HTML Dashboards**

## Contributing

See the main [CONTRIBUTING.md](../../../../CONTRIBUTING.md) for guidelines.

For Craft-specific development:

1. Set `ENABLE_CRAFT=true` in your environment
2. Use the Kubernetes/Firecracker sandbox path; see [docs/craft/dev/local-kubernetes.md](/docs/craft/dev/local-kubernetes.md) for setup

## License

MIT — see [LICENSE](../../../../LICENSE)
