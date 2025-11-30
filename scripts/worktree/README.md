# Onyx Worktree Scripts

Python scripts for managing git worktree instances with isolated Docker containers and dynamic port allocation.

## Overview

These scripts enable running multiple Onyx instances simultaneously using git worktrees. Each worktree gets:
- **Isolated Docker containers** with unique names and volumes
- **Dynamically allocated ports** to avoid conflicts
- **Independent configuration** via `.vscode/.env`
- **Generated VSCode launch configuration** from template

## Scripts

### `setup_worktree.py`

**Purpose**: Initial setup script for a new worktree instance.

**What it does**:
1. Detects worktree name from the current directory path
2. Finds available ports for all services (tries base+10, base+20, base+30...)
3. Preserves existing environment settings (API keys, feature flags, etc.) from main repo
4. Generates `.vscode/.env` with allocated ports and preserved settings
5. Generates `.vscode/launch.json` from `.vscode/launch.template.jsonc`
6. Creates a quick-start guide at `plans/worktree-quick-start.md`

**Usage**:
```bash
cd /path/to/worktree
python3 scripts/worktree/setup_worktree.py
```

**Example Output**:
```
Onyx Worktree Setup
==================

Detected worktree: dev1

Finding available ports...
✓ Next.js Web: 3010
✓ API Server: 8090
✓ Model Server: 9010
✓ Slack Bot Metrics: 8010
✓ PostgreSQL: 5442
✓ Redis: 6389
✓ Vespa: 8091
✓ Vespa Tenant: 19081
✓ MinIO API: 9014
✓ MinIO Console: 9015

Generated files:
  ✓ .vscode/.env
  ✓ .vscode/launch.json
  ✓ plans/worktree-quick-start.md

Container naming:
  Prefix: onyx_dev1
  Example: onyx_dev1_postgres

Next steps:
1. Start containers: python3 scripts/worktree/start_containers.py
2. Open VSCode Run & Debug
3. Launch "Run All Onyx Services"
4. Access at http://localhost:3010
```

**Port Allocation**:
- **Base ports**: 3000 (web), 8080 (API), 9000 (model), 5432 (postgres), etc.
- **Increment**: 10 per attempt
- **Max attempts**: 20
- **Example**: If 3000 is taken, tries 3010, 3020, 3030...

**Environment Settings Preserved**:
- API keys (GEN_AI_API_KEY, OPENAI_API_KEY, etc.)
- Feature flags (ENABLE_*, DISABLE_*)
- Service URLs (unless port-related)
- Authentication tokens
- All other non-port settings

**Environment Settings Regenerated**:
- All port numbers (PORT, APP_PORT, MODEL_SERVER_PORT, etc.)
- Service URLs that include ports (WEB_DOMAIN, INTERNAL_URL, S3_ENDPOINT_URL)
- Container configuration (CONTAINER_PREFIX, WORKTREE_NAME)

### `start_containers.py`

**Purpose**: Start and manage Docker containers for the worktree instance.

**What it does**:
1. Reads configuration from `.vscode/.env`
2. Stops any existing containers with the same prefix
3. Starts PostgreSQL, Vespa, Redis, and MinIO containers
4. Runs Alembic migrations
5. Waits for services to be ready

**Usage**:
```bash
# The script automatically loads .vscode/.env
cd /path/to/worktree
python3 scripts/worktree/start_containers.py
```

**Note**: The script automatically loads `.vscode/.env` and validates the configuration. You do NOT need to manually `source .vscode/.env`.

**Or from VSCode**:
- Open Run & Debug panel (Cmd+Shift+D)
- Select "Start Worktree Containers"
- Click Start

**Example Output**:
```
Stopping existing containers...
Starting PostgreSQL container...
Starting Vespa container...
Starting Redis container...
Starting MinIO container...
Waiting for PostgreSQL to be ready...
Running Alembic migration...
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> abc123, initial schema

Containers started successfully!
```

**Container Names**:
- Format: `{CONTAINER_PREFIX}_{service}`
- Example for worktree "dev1":
  - `onyx_dev1_postgres`
  - `onyx_dev1_redis`
  - `onyx_dev1_vespa`
  - `onyx_dev1_minio`

**Volume Names**:
- Format: `{CONTAINER_PREFIX}_{service}_data`
- Example for worktree "dev1":
  - `onyx_dev1_postgres_data`
  - `onyx_dev1_redis_data`
  - `onyx_dev1_vespa_data`
  - `onyx_dev1_minio_data`

## Workflow

### First-Time Setup

```bash
# 1. Create worktree
cd ~/onyx
git worktree add ~/onyx-worktrees/dev1 -b feature/my-feature

# 2. Navigate to worktree
cd ~/onyx-worktrees/dev1

# 3. Run setup script
python3 scripts/worktree/setup_worktree.py

# 4. Start containers
python3 scripts/worktree/start_containers.py

# 5. Open in VSCode
code .

# 6. Launch services
# Run & Debug → "Run All Onyx Services" → Start
```

### Daily Development

```bash
# Start containers (if stopped)
cd ~/onyx-worktrees/dev1
python3 scripts/worktree/start_containers.py

# Launch services from VSCode
# Run & Debug → "Run All Onyx Services"
```

### Switching Between Worktrees

Each worktree runs independently with its own ports and containers:

```bash
# Main instance
cd ~/onyx
# Uses: localhost:3000, containers: onyx_postgres, onyx_redis, etc.

# dev1 worktree
cd ~/onyx-worktrees/dev1
python3 scripts/worktree/start_containers.py
# Uses: localhost:3010, containers: onyx_dev1_postgres, onyx_dev1_redis, etc.

# dev2 worktree
cd ~/onyx-worktrees/dev2
python3 scripts/worktree/start_containers.py
# Uses: localhost:3020, containers: onyx_dev2_postgres, onyx_dev2_redis, etc.
```

## Configuration Files

### `.vscode/.env`

Generated by `setup_worktree.py`, contains all environment variables:

```bash
# Worktree Configuration
WORKTREE_NAME=dev1
CONTAINER_PREFIX=onyx_dev1

# Application Ports
PORT=3010
APP_PORT=8090
MODEL_SERVER_PORT=9010

# Infrastructure Ports
POSTGRES_PORT=5442
REDIS_PORT=6389
VESPA_PORT=8091
VESPA_TENANT_PORT=19081
MINIO_PORT=9014
MINIO_CONSOLE_PORT=9015

# Service URLs
WEB_DOMAIN=http://localhost:3010
INTERNAL_URL=http://localhost:8090

# Preserved settings from main repo
GEN_AI_API_KEY=sk-proj-...
OPENAI_API_KEY=sk-proj-...
# ... other settings ...
```

### `.vscode/launch.template.jsonc`

Template file used to generate `.vscode/launch.json`. Contains placeholders:
- `${PORT}` - Web server port
- `${APP_PORT}` - API server port
- `${MODEL_SERVER_PORT}` - Model server port

**Do not edit** `.vscode/launch.json` directly - changes will be overwritten when you re-run `setup_worktree.py`.

## Container Management

### View Running Containers

```bash
# All containers for this worktree
docker ps | grep dev1

# Specific container
docker ps | grep dev1_postgres
```

### Stop Containers

```bash
# Stop all worktree containers
docker stop onyx_dev1_postgres onyx_dev1_redis onyx_dev1_vespa onyx_dev1_minio

# Stop specific container
docker stop onyx_dev1_postgres
```

### Restart Containers

```bash
python3 scripts/worktree/start_containers.py
```

### View Logs

```bash
# View logs
docker logs onyx_dev1_postgres

# Follow logs
docker logs -f onyx_dev1_postgres
```

### Clean Up Data

```bash
# Remove all volumes (⚠️ deletes all data!)
docker volume rm onyx_dev1_postgres_data onyx_dev1_redis_data onyx_dev1_vespa_data onyx_dev1_minio_data

# Remove specific volume
docker volume rm onyx_dev1_postgres_data
```

## Troubleshooting

### Port Already in Use

**Symptom**: Error binding to port

**Solution**:
```bash
# Check what's using the port
lsof -i :3010

# Kill the process or re-run setup to allocate new ports
python3 scripts/worktree/setup_worktree.py
```

### Container Fails to Start

**Symptom**: Container immediately exits

**Solution**:
```bash
# Check container logs
docker logs onyx_dev1_postgres

# Remove and recreate
docker rm onyx_dev1_postgres
python3 scripts/worktree/start_containers.py
```

### Migration Fails

**Symptom**: Alembic migration errors

**Solution**:
```bash
# Verify environment is sourced
source .vscode/.env

# Check database connection
psql -h localhost -p $POSTGRES_PORT -U postgres -c "SELECT version();"

# Run migrations manually
cd backend
alembic upgrade head
```

### Service Won't Start in VSCode

**Symptom**: Service fails to launch

**Diagnosis**:
1. Check `.vscode/.env` exists
2. Check `.vscode/launch.json` exists
3. Verify containers are running: `docker ps | grep dev1`

**Solution**:
```bash
# Regenerate configuration
python3 scripts/worktree/setup_worktree.py

# Restart VSCode
# Try launching services again
```

## Advanced Usage

### Custom Port Allocation

Edit `scripts/setup_worktree.py` to customize:
- `increment`: Port increment per attempt (default: 10)
- `max_attempts`: Maximum attempts to find available port (default: 20)
- Base ports for each service

### Preserving Additional Settings

Edit `load_existing_env_settings()` in `setup_worktree.py` to add variables to `EXCLUDED_VARS` if you want them regenerated instead of preserved.

### Manual Configuration

You can manually edit `.vscode/.env` after generation, but changes will be lost if you re-run `setup_worktree.py`. To make permanent changes:
1. Edit `.vscode/launch.template.jsonc` for launch config changes
2. Edit `scripts/setup_worktree.py` for environment variable defaults

## Files Generated

| File | Description | Commit? |
|------|-------------|---------|
| `.vscode/.env` | Environment variables with allocated ports | No (gitignored) |
| `.vscode/launch.json` | VSCode debug configuration | No (gitignored) |
| `plans/worktree-quick-start.md` | Quick reference guide | No (optional) |

## Files to Commit

| File | Description |
|------|-------------|
| `scripts/setup_worktree.py` | Setup script |
| `scripts/start_containers.py` | Container manager |
| `.vscode/launch.template.jsonc` | Launch config template |
| `scripts/README.md` | This file |

## References

- **Quick Start Guide**: `plans/worktree-quick-start.md` (generated per-worktree)
- **Implementation Plan**: `plans/worktree-port-allocation-plan.md`
- **Git Worktrees**: https://git-scm.com/docs/git-worktree
- **Onyx Docs**: https://docs.onyx.app/
