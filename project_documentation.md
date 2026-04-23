# InsightAI Project Documentation

> Forked from [Onyx](https://github.com/onyx-dot-app/onyx) (formerly Danswer) — an open-source
> Gen-AI and Enterprise Search platform that connects to company documents, apps, and people.

---

## Table of Contents

1. [Tech Stack](#1-tech-stack)
2. [App Components](#2-app-components)
3. [App Modules](#3-app-modules)
4. [Local Development Deployment](#4-local-development-deployment)
5. [Creating Accounts for Testing](#5-creating-accounts-for-testing)
6. [Branding and Upstream Sync](#6-branding-and-upstream-sync)

---

## 0. Rebrand Overview (InsightAI)

This repository is a shallow, upstream-safe rebrand of Onyx. Internal
identifiers (Python package `onyx/`, Docker image names `onyxdotapp/onyx-*`,
Helm chart `onyx`, cookie `onyx_tid`, Vespa `danswer_chunk`, Tauri bundle id,
etc.) are deliberately left unchanged so that merging `upstream/main` stays
low-conflict. All user-visible branding is driven by:

1. **Runtime Enterprise Settings** (preferred) — the `application_name`,
   custom logo, and custom logotype are stored in the KV store + file store.
   Seed with `scripts/insightai_brand.py` or change via the Admin > Theme UI
   at `/admin/theme`. No source diff required.
2. **A small set of fallback defaults** in code for when Enterprise Settings
   are unavailable (first boot, EE disabled). See
   [Section 6](#6-branding-and-upstream-sync) for the exact file list.
3. **Static brand assets** at well-known paths that are overwritten in place
   (same filenames as upstream). See [Section 6](#6-branding-and-upstream-sync).

---

## 1. Tech Stack

### Backend

| Technology | Version | Purpose |
|---|---|---|
| **Python** | 3.11 | Core language |
| **FastAPI** | 0.133.1 | REST API framework |
| **SQLAlchemy** | 2.0.15 | ORM and database models (`DeclarativeBase`, `Mapped`, `mapped_column`) |
| **Alembic** | latest | Database migrations (separate chains for main and tenant schemas) |
| **Celery** | 5.5.1 | Distributed task queue for background workers |
| **Pydantic** | 2.11.7 | Data validation and settings |
| **Uvicorn** | 0.35.0 | ASGI server |
| **LiteLLM** | 1.81.6 | Multi-provider LLM gateway |
| **OpenAI SDK** | 2.14.0 | OpenAI API client |
| **LangChain Core** | latest | LLM orchestration |
| **fastapi-users** | latest | Auth (JWT, cookie, OAuth, SAML) |
| **asyncpg / psycopg2** | latest | PostgreSQL drivers |
| **Redis** | latest | Caching and inter-process coordination |
| **Playwright** (Python) | latest | Web connector (headless browser scraping) |
| **Supervisor** | latest | Process manager for backend services |
| **uv** | 0.9.9 | Python package manager (replaces pip) |

### Frontend (Web)

| Technology | Version | Purpose |
|---|---|---|
| **Next.js** | 16.1.7 | React framework (App Router, SSR, API proxy) |
| **React** | 19.2.4 | UI library |
| **TypeScript** | 5.9.x | Type-safe JavaScript |
| **Tailwind CSS** | 3.4.17 | Utility-first styling with custom design token system |
| **Radix UI** | various | Accessible UI primitives (dialog, dropdown, tabs, tooltip, etc.) |
| **Headless UI** | latest | Additional unstyled components |
| **Zustand** | 5.x | Lightweight client-side state management |
| **SWR** | 2.x | Server-state fetching and caching |
| **Formik + Yup** | latest | Form handling and validation |
| **motion** (Framer) | latest | Animations |
| **next-themes** | latest | Dark/light mode theming |
| **Storybook** | 8.6 | Component documentation and visual testing |
| **Playwright** (TS) | latest | E2E browser testing |
| **Jest** | latest | Unit and integration testing |
| **Sentry** | latest | Error monitoring |
| **PostHog** | latest | Product analytics (EE) |
| **Stripe** | latest | Billing integration (EE) |

### Design System: Opal

The frontend uses **Opal** (`web/lib/opal/`) as its design system — a local workspace package
(`@onyx/opal`) providing layout primitives, buttons, text rendering, interactive surfaces, and
a full CSS-variable-based color system with automatic dark mode.

### Desktop App

| Technology | Version | Purpose |
|---|---|---|
| **Tauri** | 2.x | Lightweight native desktop shell (Rust backend + WebKit) |
| **Rust** | latest | Tauri backend (`desktop/src-tauri/`) |
| **@tauri-apps/api** | 2.10.1 | JavaScript bridge to native APIs |

The desktop app is a thin macOS/Linux wrapper around the Onyx Cloud web interface.

### Embeddable Widget

| Technology | Version | Purpose |
|---|---|---|
| **Lit** | 3.x | Web Components framework |
| **Vite** | 7.x | Build tool (library mode) |
| **marked** | 12.x | Markdown rendering |
| **DOMPurify** | 3.x | HTML sanitization |

Ships as a single `onyx-widget.js` file that renders a `<onyx-chat-widget>` custom element
in Shadow DOM. Supports both cloud and self-hosted backends.

### CLI

| Technology | Purpose |
|---|---|
| **Go** + **Bubble Tea** | Terminal UI for chatting with Onyx |
| Published to PyPI as `onyx-cli` | Cross-platform binary wheels |

### Infrastructure & Data Stores

| Service | Purpose |
|---|---|
| **PostgreSQL 15** | Relational data (users, connectors, chat sessions, documents metadata) |
| **Vespa** | Vector database and search engine |
| **OpenSearch** | Full-text search (optional, alongside Vespa) |
| **Redis** | Caching, Celery broker, session store, inter-process coordination |
| **MinIO** | S3-compatible object storage for files |
| **Nginx** | Reverse proxy and TLS termination |
| **Docker + Docker Compose** | Container orchestration |
| **Helm** | Kubernetes deployment |
| **Terraform** | AWS infrastructure provisioning (VPC, EKS, RDS, ElastiCache, S3) |

### ML / Model Server

| Technology | Version | Purpose |
|---|---|---|
| **PyTorch** | 2.9.1 | ML framework |
| **Transformers** | 4.53.0 | Hugging Face model loading |
| **SentenceTransformers** | 4.0.2 | Embedding generation |
| **Default model** | `nomic-ai/nomic-embed-text-v1` | Text embeddings |

The model server runs as a separate FastAPI service on port 9000, with two instances in
production: one for inference (real-time queries) and one for indexing (batch document processing).

---

## 2. App Components

### High-Level Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                         Clients                               │
│  Web Browser  │  Desktop (Tauri)  │  Widget  │  CLI  │  API  │
└───────┬───────┴─────────┬─────────┴────┬─────┴───┬───┴───┬───┘
        │                 │              │         │       │
        ▼                 ▼              ▼         ▼       ▼
┌───────────────────────────────────────────────────────────────┐
│                      Nginx (Port 80/443)                      │
└───────────────┬──────────────────────┬────────────────────────┘
                │                      │
        ┌───────▼───────┐      ┌───────▼───────┐
        │  Web Server   │      │  API Server   │
        │  (Next.js)    │      │  (FastAPI)    │
        │  Port 3000    │      │  Port 8080    │
        └───────────────┘      └───────┬───────┘
                                       │
                ┌──────────────────────┼──────────────────────┐
                │                      │                      │
        ┌───────▼───────┐      ┌───────▼───────┐     ┌───────▼───────┐
        │  Background   │      │ Model Servers │     │  MCP Server   │
        │  Workers      │      │ (Embeddings)  │     │  (Optional)   │
        │  (Celery)     │      │ Port 9000     │     └───────────────┘
        └───────┬───────┘      └───────────────┘
                │
     ┌──────────┼──────────┬──────────────┐
     │          │          │              │
┌────▼───┐ ┌───▼───┐ ┌────▼────┐  ┌──────▼──────┐
│Postgres│ │ Redis │ │  Vespa  │  │   MinIO     │
│        │ │       │ │         │  │   (S3)      │
└────────┘ └───────┘ └─────────┘  └─────────────┘
```

### Service Breakdown

#### 1. Web Server (`web/`)

The Next.js application serving the user interface. Uses the App Router with these main areas:

| Route | Purpose |
|---|---|
| `/app` | Main chat interface and AI assistant |
| `/admin` | Admin dashboard (users, connectors, LLM config, theming) |
| `/auth` | Login, signup, OAuth callbacks |
| `/craft` | Onyx Craft (build/streaming UI, onboarding) |
| `/ee` | Enterprise features (billing, groups, performance, analytics) |
| `/nrf` | Side-panel interface |
| `/api/[...path]` | Dev proxy to backend API |

In production, Nginx routes `/api/*` to the FastAPI backend and everything else to Next.js.

#### 2. API Server (`backend/onyx/`)

FastAPI application providing all REST endpoints. Key router groups:

| Area | Endpoints |
|---|---|
| **Auth** | `/auth/register`, `/auth/login`, `/auth/logout`, OAuth, SAML, API keys, PATs |
| **Chat** | `/chat/...` — message processing, LLM loop, streaming, citations |
| **Search** | `/query/...` — document retrieval, federated search |
| **Connectors** | `/connector/...` — CRUD for data source connections |
| **Documents** | `/document/...` — document management, indexing status |
| **Admin** | `/manage/...` — users, LLM providers, embedding models, settings |
| **Agents** | `/persona/...` — AI assistant configuration |
| **Tools** | Web search, URL reader, Python interpreter, MCP, image generation |
| **Knowledge Graph** | `/kg/...` — KG extraction and clustering |
| **Voice** | `/voice/...` — TTS providers (OpenAI, ElevenLabs, Azure) |

#### 3. Background Workers (Celery via Supervisor)

| Worker | Queue(s) | Responsibility |
|---|---|---|
| **Primary** | `celery` | Connector management, doc sync, LLM updates, periodic checks |
| **Light** | `vespa_metadata_sync`, `connector_deletion`, `doc_permissions_upsert`, `checkpoint_cleanup`, `index_attempt_cleanup` | Fast, lightweight operations |
| **Heavy** | `connector_pruning`, `connector_doc_permissions_sync`, `connector_external_group_sync`, `csv_generation` | Resource-intensive tasks |
| **Doc Fetching** | `connector_doc_fetching` | Pulls documents from external sources |
| **Doc Processing** | `docprocessing` | Indexes documents: Postgres upsert, chunking, embedding, Vespa write |
| **User File Processing** | `user_file_processing`, `user_file_project_sync`, `user_file_delete` | User-uploaded file handling |
| **Monitoring** | `monitoring` | System health, queue metrics, memory tracking |
| **Beat** | (scheduler) | Periodic task scheduling (indexing every 15s, deletion checks every 20s, etc.) |

#### 4. Model Server (`backend/model_server/`)

Dedicated FastAPI service for ML inference:
- `/encoder` — generates text embeddings using SentenceTransformers
- `/api/health` — health check
- `/api/gpu-status` — GPU availability

Two instances run in production: `inference_model_server` (real-time) and `indexing_model_server` (batch).

#### 5. Desktop App (`desktop/`)

Tauri 2 application — a lightweight native wrapper that loads the Onyx Cloud web interface in a
WebKit webview. Provides macOS keyboard shortcuts, window state persistence, and native
title bar. No offline capability; requires a running Onyx server.

#### 6. Embeddable Widget (`widget/`)

A Lit-based web component (`<onyx-chat-widget>`) for embedding Onyx chat on third-party sites.
Ships as a single JS file. Supports SSE streaming, markdown rendering, and both cloud/self-hosted
deployment modes.

#### 7. CLI (`cli/`)

A Go-based terminal UI for chatting with Onyx from the command line. Commands: `ask`, `agents`,
`serve` (SSH TUI server), `validate-config`. Configured via `~/.config/onyx-cli/config.json`
or environment variables.

#### 8. Bots

| Bot | Location |
|---|---|
| **Slack Bot** | `backend/onyx/onyxbot/` — listens for Slack events and responds via Onyx |
| **Discord Bot** | `backend/onyx/onyxbot/` — Discord integration |

Both run as separate supervisor processes.

---

## 3. App Modules

### Backend Modules (`backend/onyx/`)

| Module | Description |
|---|---|
| `auth/` | Authentication — fastapi-users integration, JWT/cookie transports, Redis session strategy, OAuth (Google, OIDC), SAML, API keys, PATs, email verification, invites, anonymous users |
| `background/` | Celery workers, beat schedule, indexing pipeline (fetch → chunk → embed → write), monitoring |
| `cache/` | Pluggable cache layer with Redis and Postgres backends |
| `chat/` | Chat message processing, LLM conversation loop, citation extraction, streaming responses |
| `configs/` | Application configuration — env-var-driven settings for auth, models, embeddings, constants |
| `connectors/` | 50+ data source connectors (see full list below) |
| `context/search/` | Search retrieval pipeline, query preprocessing, federated search |
| `db/` | SQLAlchemy models, database operations organized by domain (users, documents, connectors, personas, etc.) |
| `document_index/` | Vespa and OpenSearch integration — document indexing, vector search |
| `error_handling/` | Centralized error codes and `OnyxError` exception hierarchy |
| `federated_connectors/` | External search (e.g. federated Slack search) |
| `file_store/` | File storage abstraction over MinIO/S3/local |
| `hooks/` | Lifecycle hooks registry for extensibility |
| `kg/` | Knowledge graph — entity extraction, relationship building, clustering |
| `llm/` | LLM provider wiring via LiteLLM — supports OpenAI, Anthropic, Google, Cohere, and others |
| `mcp_server/` | Model Context Protocol server implementation |
| `onyxbot/` | Slack and Discord bot listeners |
| `prompts/` | Prompt templates for chat, search, and agent actions |
| `redis/` | Redis helpers — locks, queues, connector coordination |
| `search/` | Search logic, result ranking, and filtering |
| `secondary_llm_flows/` | Auxiliary LLM workflows (summarization, classification, etc.) |
| `server/` | FastAPI routers, middleware, metrics, OpenAPI |
| `tools/` | Agent tools — web search, URL reader, Python interpreter, MCP client, memory, images, custom OpenAPI tools |
| `tracing/` | OpenTelemetry tracing, Langfuse and Braintrust integration |
| `utils/` | Logging, encryption, tenant context, batching, middleware utilities |
| `voice/` | Voice/TTS providers — OpenAI, ElevenLabs, Azure |
| `setup.py` | Application startup — DB checks, index initialization, default connector seeding |
| `main.py` | FastAPI app assembly and router registration |

### Enterprise Edition (`backend/ee/`)

| Module | Description |
|---|---|
| `server/` | Analytics, billing, license management, SCIM (user provisioning), tenant management, query history, usage export, token rate limits |
| `db/` | EE-specific database operations |
| `external_permissions/` | Per-connector permission sync (Confluence, Jira, Google Drive, GitHub, Salesforce, SharePoint, Slack, Teams, Gmail) |
| `feature_flags/` | PostHog feature flag provider |
| `configs/` | EE-specific configuration |
| `utils/` | License validation, PostHog telemetry, encryption |

### Supported Connectors (50+)

Airtable, Asana, Axero, Bitbucket, Blob Storage, Bookstack, Canvas, ClickUp, Coda,
Confluence, Discourse, Discord, Document360, Dropbox, Drupal Wiki, Egnyte, File Upload,
Fireflies, Freshdesk, Gitbook, GitHub, GitLab, Gmail, Gong, Google Drive, Google Sites,
Guru, Highspot, HubSpot, IMAP (Email), Jira, Linear, Loopio, MediaWiki, Microsoft Teams,
Notion, Outline, Productboard, Request Tracker, Salesforce, SharePoint, Slab, Slack,
Teams, TestRail, Web Scraper, Wikipedia, Xenforo, Zendesk, Zulip.

### Frontend Modules (`web/src/`)

| Directory | Description |
|---|---|
| `app/` | Next.js App Router — pages, layouts, API route handlers per feature area |
| `app/app/` | Main authenticated product (chat shell, stores) |
| `app/admin/` | Admin UI (users, connectors, LLM config, theme, embeddings) |
| `app/auth/` | Login, signup, OAuth flows |
| `app/craft/` | Onyx Craft (build/streaming UI, onboarding) |
| `app/ee/` | Enterprise features (billing, groups, analytics, theme) |
| `components/` | **Legacy** — being phased out in favor of Opal |
| `components/ui/` | Shared Radix-based primitives (tooltip, etc.) |
| `refresh-components/` | Production UI components (buttons, inputs, modals, messages, popovers, loaders, skeletons) |
| `sections/` | Feature-specific composites (sidebar, cards, modals) |
| `layouts/` | Reusable page layouts (settings, app, tables, actions) |
| `lib/` | URL builders, API fetchers, feature clients (chat, billing, build), constants |
| `hooks/` | Domain-specific hooks (agents, chat, admin, voice — one hook per file) |
| `providers/` | App-wide React contexts (SWR, user, toast, voice, sidebar) |
| `icons/` | Curated SVG icon set (preferred over external icon libraries) |

### Database Schema (Key Tables)

The database is managed via SQLAlchemy models in `backend/onyx/db/models.py`. Major entity groups:

- **Users & Auth** — users, OAuth accounts, access tokens, API keys, PATs, invites
- **Connectors** — connector configs, credentials, indexing attempts, document metadata
- **Chat** — chat sessions, messages, citations, feedback, agents/personas
- **Documents** — document store, document sets, tags, boost values
- **Search** — search settings, embedding models, query logs
- **Knowledge Graph** — KG entities, relationships, clusters
- **Enterprise** — user groups, SAML configs, SCIM data, token rate limits, analytics

---

## 4. Local Development Deployment

### Prerequisites

| Requirement | Version | Install |
|---|---|---|
| **Python** | 3.11 (exact) | `brew install python@3.11` or pyenv |
| **Node.js** | 22.x | `nvm install 22 && nvm use 22` |
| **Docker** | latest | [Docker Desktop](https://www.docker.com/products/docker-desktop/) |
| **uv** | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

### Option A: Hybrid Development (Recommended)

Run infrastructure in Docker, application services on host for hot-reload.

#### Step 1: Clone and install dependencies

```bash
# Python
uv venv .venv --python 3.11
source .venv/bin/activate
uv sync --all-extras
uv run playwright install

# Node.js (in web/ directory)
cd web && npm i && cd ..
```

#### Step 2: Start infrastructure containers

```bash
cd deployment/docker_compose
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d \
  index relational_db cache minio
```

This starts:
- **Postgres** on port `5432`
- **Vespa** on ports `19071` / `8081`
- **Redis** on port `6379`
- **MinIO** on ports `9004` / `9005`

#### Step 3: Run database migrations (first time only)

```bash
cd backend
alembic upgrade head
```

Re-run this after pulling changes that include new migrations.

#### Step 4: Start application services

Open four terminal sessions from the project root:

**Terminal 1 — Web Server (Next.js)**
```bash
cd web
npm run dev
```

**Terminal 2 — Model Server**
```bash
cd backend
source ../.venv/bin/activate
uvicorn model_server.main:app --reload --port 9000
```

**Terminal 3 — Background Jobs (Celery)**
```bash
cd backend
source ../.venv/bin/activate
python ./scripts/dev_run_background_jobs.py
```

**Terminal 4 — API Server (FastAPI)**
```bash
cd backend
source ../.venv/bin/activate
AUTH_TYPE=basic uvicorn onyx.main:app --reload --port 8080
```

#### Step 5: Access the app

Open **http://localhost:3000** — you should see the onboarding wizard.

### Option B: Full Docker Stack

Run everything in containers (no hot-reload, but simpler setup).

```bash
cd deployment/docker_compose

# Standard
docker compose up -d

# With exposed dev ports (Postgres, Redis, Vespa, etc.)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --wait
```

Access at **http://localhost:3000**.

To rebuild after code changes:

```bash
docker compose up -d --build
```

### Desktop App (Tauri)

Requires Rust toolchain and Tauri CLI. The desktop app connects to a running Onyx instance
(cloud or local).

```bash
cd desktop
npm install
npm run dev     # Development with hot-reload
npm run build   # Production build
```

Platform-specific builds:
```bash
npm run build:dmg     # macOS universal binary
npm run build:linux   # Linux .deb and .rpm
```

### Widget

```bash
cd widget
npm install
npm run dev              # Dev server
npm run build:cloud      # Cloud build
npm run build:self-hosted  # Self-hosted build (uses VITE_WIDGET_BACKEND_URL)
```

Configure self-hosted mode via `widget/.env`:
```env
VITE_WIDGET_BACKEND_URL=http://localhost:3000
VITE_WIDGET_API_KEY=your-api-key
```

### Mobile

There is **no native mobile app** in this codebase. Mobile access is via the responsive web
interface or the embeddable widget (which supports mobile fullscreen mode).

### Environment Variables

The primary env configuration lives in `deployment/docker_compose/env.template`. Key variables:

| Variable | Default | Purpose |
|---|---|---|
| `AUTH_TYPE` | `basic` | Auth method: `basic`, `google_oauth`, `oidc`, `saml`, `cloud` |
| `POSTGRES_HOST` | `relational_db` | Postgres hostname |
| `VESPA_HOST` | `index` | Vespa hostname |
| `REDIS_HOST` | `cache` | Redis hostname |
| `MODEL_SERVER_HOST` | `inference_model_server` | Embedding model server |
| `INTERNAL_URL` | `http://api_server:8080` | Backend URL (used by web server for SSR) |
| `ENABLE_PAID_ENTERPRISE_EDITION_FEATURES` | `false` | Toggle EE features |
| `FILE_STORE_BACKEND` | `s3` | File storage: `s3` (MinIO) or `postgres` |
| `USER_AUTH_SECRET` | (generate) | JWT signing secret |
| `ENCRYPTION_KEY_SECRET` | (generate) | Credential encryption key |

For local hybrid dev, most defaults work. The web server proxies `/api/*` to `http://localhost:8080`
automatically.

### Formatting and Linting

```bash
# Backend (from repo root, with venv active)
uv run pre-commit install
uv run pre-commit run --all-files
uv run mypy .   # from backend/ directory

# Frontend (from web/)
npx prettier --write .
```

### Useful Dev Commands

| Task | Command |
|---|---|
| Reset Postgres | `cd backend && python scripts/reset_postgres.py` |
| Connect to Postgres | `docker exec -it onyx-relational_db-1 psql -U postgres` |
| Run unit tests | `source .venv/bin/activate && pytest -xv backend/tests/unit` |
| Run integration tests | `source .venv/bin/activate && python -m dotenv -f .vscode/.env run -- pytest backend/tests/integration` |
| Run E2E tests | `cd web && npx playwright test` |
| Storybook | `cd web && npm run storybook` |
| View logs | Check `backend/log/<service_name>_debug.log` |

---

## 5. Creating Accounts for Testing

### First User (Automatic Admin)

1. Start the application (either hybrid or full Docker).
2. Navigate to **http://localhost:3000**.
3. Complete the onboarding wizard (connect an LLM provider).
4. Register with any email and password.

The **first registered user automatically becomes an Admin**. This is enforced in
`backend/onyx/db/auth.py` — when `user_count == 0`, the role is set to `UserRole.ADMIN`.

### Subsequent Users (Basic Role)

All users registered after the first one are assigned `UserRole.BASIC` by default.

### Auth Methods

| Method | `AUTH_TYPE` | Setup |
|---|---|---|
| **Email/Password** | `basic` | Default. No additional config needed. |
| **Google OAuth** | `google_oauth` | Set `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` in `.env` |
| **OpenID Connect** | `oidc` | Set `OPENID_CONFIG_URL`, `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET` |
| **SAML** | `saml` | Configure `SAML_CONF_DIR` with IdP metadata |
| **Cloud** (multi-tenant) | `cloud` | Used for multi-tenant SaaS deployments |

### Invite Flow

Admins can invite users through the admin UI:

1. Log in as admin.
2. Go to **Admin** > **Users**.
3. Enter email addresses to invite.
4. Invited users receive a signup link with their email pre-filled.

Invitations are managed via `backend/onyx/auth/invited_users.py`. For `SAML` and `OIDC` auth
types, invite verification is skipped (JIT provisioning).

### Quick Test Credentials

For E2E testing with Playwright, the default test account is:

| Field | Value |
|---|---|
| Email | `a@example.com` |
| Password | `a` |

This works when the app has been seeded with this test user (standard in E2E test setup).

### User Roles

| Role | Permissions |
|---|---|
| `ADMIN` | Full access — manage users, connectors, LLM providers, settings, view analytics |
| `BASIC` | Standard access — chat, search, use connectors, manage own settings |
| `CURATOR` (EE) | Manage document sets and connector permissions |
| `GLOBAL_CURATOR` (EE) | Curator across all groups |
| `SLACK_USER` | Bot-only access |
| `EXTERNAL_PERMISSIONED_USER` | Access controlled by external permission systems |
| `LIMITED` | Restricted access |

### API Key Authentication

For programmatic access (CLI, widget, integrations):

1. Log in as admin.
2. Navigate to **Admin** > **API Keys**.
3. Create a new API key.
4. Use the key in the `Authorization: Bearer <key>` header.

Personal Access Tokens (PATs) are also supported for user-scoped API access.

### Promoting Users

To promote a user to admin via the database:

```bash
docker exec -it onyx-relational_db-1 psql -U postgres -c \
  "UPDATE \"user\" SET role = 'admin' WHERE email = 'user@example.com';"
```

Or through the admin UI at **Admin** > **Users** > select user > change role.

---

## Appendix: Directory Structure

```
InsightAI/
├── backend/                    # Python backend
│   ├── onyx/                   # Core application
│   │   ├── auth/               # Authentication & authorization
│   │   ├── background/         # Celery workers & task definitions
│   │   ├── cache/              # Redis/Postgres cache layer
│   │   ├── chat/               # Chat & LLM interaction
│   │   ├── configs/            # App configuration
│   │   ├── connectors/         # 50+ data source connectors
│   │   ├── context/search/     # Search retrieval pipeline
│   │   ├── db/                 # SQLAlchemy models & DB operations
│   │   ├── document_index/     # Vespa/OpenSearch integration
│   │   ├── error_handling/     # Centralized error codes
│   │   ├── kg/                 # Knowledge graph
│   │   ├── llm/                # LLM provider integration
│   │   ├── server/             # FastAPI routers & middleware
│   │   ├── tools/              # Agent tools
│   │   ├── voice/              # TTS providers
│   │   └── main.py             # App entry point
│   ├── ee/                     # Enterprise Edition
│   ├── model_server/           # ML embedding server
│   ├── alembic/                # DB migrations (main schema)
│   ├── alembic_tenants/        # DB migrations (tenant schema)
│   ├── scripts/                # Dev & ops utilities
│   └── tests/                  # Unit, integration, E2E tests
├── web/                        # Next.js frontend
│   ├── src/app/                # App Router pages & layouts
│   ├── src/refresh-components/ # Production UI components
│   ├── src/sections/           # Feature composites
│   ├── src/layouts/            # Page layouts
│   ├── src/hooks/              # Custom React hooks
│   ├── src/providers/          # Context providers
│   ├── src/icons/              # SVG icon set
│   ├── src/lib/                # Utilities & API clients
│   ├── lib/opal/               # Opal design system
│   ├── tailwind-themes/        # Theme configuration
│   └── tests/                  # Jest & Playwright tests
├── desktop/                    # Tauri desktop app
│   ├── src/                    # Frontend (HTML/JS)
│   └── src-tauri/              # Rust backend
├── widget/                     # Embeddable chat widget (Lit)
│   └── src/                    # Widget source
├── cli/                        # Go CLI tool
├── deployment/                 # Deployment configs
│   ├── docker_compose/         # Docker Compose files & env templates
│   ├── helm/                   # Kubernetes Helm charts
│   ├── terraform/              # AWS Terraform modules
│   └── aws_ecs_fargate/        # CloudFormation for ECS
├── contributing_guides/        # Developer guides
├── pyproject.toml              # Root Python project config
└── uv.lock                     # Dependency lockfile
```

---

## 6. Branding and Upstream Sync

### Upstream remote

This fork already has the upstream Onyx repo wired as a second remote:

```bash
$ git remote -v
origin    https://github.com/KoloqAI/InsightAI.git (fetch/push)
upstream  https://github.com/onyx-dot-app/onyx.git (fetch/push)
```

### Syncing with upstream

Use the helper script from the repo root:

```bash
scripts/sync_upstream.sh              # default: fetch + merge
scripts/sync_upstream.sh rebase       # fetch + rebase
scripts/sync_upstream.sh fetch-only
```

Any merge conflict should be confined to the "Branding patches" list below.
Resolve by keeping the InsightAI side, then `git add && git commit`.

### Branding patches (source code)

These five files carry hand-edited fallback defaults for the InsightAI
product name. Expected conflict surface on an upstream merge.

| File | What changed |
|---|---|
| [backend/onyx/configs/constants.py](backend/onyx/configs/constants.py) | `ONYX_DEFAULT_APPLICATION_NAME = "InsightAI"` |
| [web/src/providers/DynamicMetadata.tsx](web/src/providers/DynamicMetadata.tsx) | `document.title` fallback `"InsightAI"` |
| [web/src/app/layout.tsx](web/src/app/layout.tsx) | `metadata.title` and `metadata.description` |
| [web/src/app/auth/login/LoginText.tsx](web/src/app/auth/login/LoginText.tsx) | Welcome heading fallback `"InsightAI"` |
| [web/src/lib/constants.ts](web/src/lib/constants.ts) | `APP_SLOGAN = "AI-Powered Insight Platform"` |

Deliberately **not** patched (keeps internal identifiers upstream-compatible):

- Python package `backend/onyx/`, all `onyx.*` module paths, `Onyx*` class names
- `ONYX_*` env var names
- Docker image names `onyxdotapp/onyx-*`, Helm chart name `onyx`
- Cookie name `onyx_tid`, Vespa index names (`danswer_chunk`)
- Tauri bundle id `app.onyx.desktop`, Chrome extension id, CLI `onyx-cli`
- Inline SVG logo components (`SvgOnyxLogo`, `OnyxIcon`, `OnyxLogoTypeIcon`) — bypassed at runtime when `use_custom_logo = true`
- `LICENSE` and `backend/ee/LICENSE` — pending legal review

### Branding assets (binary files)

These are overwritten in place at the same paths used by upstream, so no
source code references change:

| Asset | Purpose |
|---|---|
| [web/public/logo.svg](web/public/logo.svg) | Generic SVG mark served at `/logo.svg` |
| `web/public/onyx.ico` | Browser favicon (filename kept intentionally so [web/src/providers/DynamicMetadata.tsx](web/src/providers/DynamicMetadata.tsx) needs no change) |
| `backend/static/images/logo.png` | Default square logo; used by `OnyxRuntime` for API + email (`cid:logo.png`) |
| `backend/static/images/logotype.png` | Default horizontal wordmark |

To regenerate the placeholder assets from the `i` mark design, rerun
[`/tmp/insightai_brand/generate_assets.py`](/) or replace with designer-produced
assets at the same paths.

### One-shot brand bootstrap

For a live environment, after infra is up and the backend can import the
`ee.onyx.*` modules, seed the Enterprise Settings KV + file store:

```bash
source .venv/bin/activate
python scripts/insightai_brand.py
```

This sets `application_name = "InsightAI"`, enables `use_custom_logo` /
`use_custom_logotype`, and uploads `backend/static/images/logo.png` and
`logotype.png` into the file store under the ids `__logo__` and
`__logotype__`. After that, the admin UI's Theme page reflects InsightAI
and every consumer of `enterpriseSettings` renders the custom branding.

Admins can later re-upload logos through the Admin > Theme UI at
`/admin/theme` without touching the filesystem.

### Image inventory (web surface, what was replaced)

Four files, all kept at their original upstream paths:

- `web/public/logo.svg`
- `web/public/onyx.ico`
- `backend/static/images/logo.png`
- `backend/static/images/logotype.png`

Not replaced (out of scope: desktop / chrome extension / widget / CLI):

- `desktop/src-tauri/icons/*` (icon.svg, tray-icon.svg, Android XML + any generated `.icns`/`.ico`/PNGs)
- `extensions/chrome/public/icon{16,32,48,128}.png`, `logo.png`
- `widget/` (no bundled images; host passes `logo=` prop)
- `backend/tests/integration/tests/pruning/website/img/logo.png` (test fixture)

