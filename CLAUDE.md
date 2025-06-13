# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Frontend (Next.js) - `/web` directory
- `npm run dev` - Start development server with Turbo
- `npm run build` - Build for production
- `npm run lint` - Run ESLint
- `npm run lint:fix-unused` - Fix unused imports
- `npm test` - Run Jest tests

### Backend (Python) - `/backend` directory
- `uvicorn onyx.main:app --reload --port 8080` - Start API server
- `uvicorn model_server.main:app --reload --port 9000` - Start model server
- `python ./scripts/dev_run_background_jobs.py` - Start Celery background workers
- `alembic upgrade head` - Run database migrations
- `python -m mypy .` - Type checking
- `python -m pytest` - Run tests

### Docker Development
- `docker compose -f docker-compose.dev.yml -p onyx-stack up -d index relational_db cache` - Start external services (Vespa, Postgres, Redis)
- `docker compose -f docker-compose.dev.yml -p onyx-stack up -d` - Start full stack

### Code Quality
- **Backend**: `ruff` for linting, `mypy` for type checking, `pre-commit` hooks
- **Frontend**: `prettier` for formatting, `eslint` for linting

## Architecture Overview

### Tech Stack
- **Backend**: FastAPI, SQLAlchemy, Celery, Redis, Vespa (search), LangChain, LiteLLM
- **Frontend**: Next.js 15, TypeScript, TailwindCSS, shadcn/ui, SWR
- **Infrastructure**: Docker, PostgreSQL, Redis, Vespa

### Core Components

#### 1. Connector System (`backend/onyx/connectors/`)
40+ connectors for data sources (Google Drive, Slack, Confluence, etc.). Each connector implements `BaseConnector` interface with standardized document ingestion patterns.

#### 2. Indexing Pipeline (`backend/onyx/indexing/`)
Handles document chunking, embedding generation, and vector database insertion. Uses Celery for async processing and Vespa for vector search.

#### 3. LLM Integration (`backend/onyx/llm/`)
Multi-provider LLM support through LiteLLM. Supports OpenAI, Anthropic, Google, Azure, and custom endpoints with unified interface.

#### 4. Agent System (`backend/onyx/agents/`)
LangGraph-based agents for complex multi-step reasoning, deep search, and tool orchestration.

#### 5. Chat Interface (`backend/onyx/chat/`)
Conversation management with streaming responses, document integration, and citations.

#### 6. Web Application (`web/src/`)
Admin interface for connectors/models/users, chat interface, and assistant gallery.

### Key Patterns
- **Plugin Architecture**: Standardized interfaces for connectors, LLM providers, and tools
- **Multi-Tenant**: Tenant isolation with RBAC
- **Event-Driven**: Redis pub/sub, Celery task queues
- **Microservices**: API server, model server, background workers, web frontend

### Database Schema
Core entities: Users, Documents, Connectors, Chat Sessions, Assistants. Uses Alembic for migrations.

### Development Setup Requirements
- Python 3.11 (virtual environment recommended outside onyx directory)
- Node.js/npm
- Docker (for Postgres, Vespa, Redis)
- Required Python packages from `backend/requirements/` files

### Authentication & Security
Supports OAuth2, SAML, OIDC, Basic Auth. Enterprise features include SSO, RBAC, credential encryption.

## Important Notes
- Always run `alembic upgrade head` for database migrations before starting
- Use `AUTH_TYPE=disabled` for local development
- Background jobs are required for document indexing and processing
- Pre-commit hooks enforce code formatting standards