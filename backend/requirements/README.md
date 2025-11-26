# Requirements Management with uv

This directory is kept for backwards compatibility with existing Docker builds.

## Overview

We use **`pyproject.toml`** as the single source of truth for all dependencies, with a unified **`uv.lock`** file for resolved versions.

### Why this approach?

- ✅ **Single source of truth**: All dependencies defined in `pyproject.toml`
- ✅ **No duplication**: Dependencies shared across environments are only listed once
- ✅ **Unified lock file**: All versions resolved together - guaranteed compatible
- ✅ **Fast**: `uv` is 10-100x faster than pip-tools
- ✅ **Reproducible builds**: Lock file pins all transitive dependencies
- ✅ **Easy updates**: Change `pyproject.toml`, run `uv lock`, done!

## File Structure

```

pyproject.toml                      # SOURCE OF TRUTH - edit this!
uv.lock                             # Unified lock file (all versions)
backend/
└── requirements/                   # Legacy .txt files (for Docker compat)
    ├── default.txt
    ├── dev.txt
    ├── ee.txt
    ├── model_server.txt
    └── combined.txt
└── scripts/
    └── compile_requirements.py     # Script to regenerate uv.lock
```

## Workflow

### 1. Installing uv

If you don't have `uv` installed:

```bash
# On macOS/Linux
curl -LsSf https://astral.py/uv/install.sh | sh
```

### 2. Adding/Updating Dependencies

**DO NOT** edit the `.txt` files directly! Instead:

1. Edit `pyproject.toml`
2. Add/update/remove dependencies in the appropriate section:
   - `[dependency-groups]` for dev tools
   - `[project.dependencies]` for **shared** dependencies (used by both backend and model_server)
   - `[project.optional-dependencies.backend]` for backend-only dependencies
   - `[project.optional-dependencies.model_server]` for model_server-only dependencies (ML packages)
   - `[project.optional-dependencies.ee]` for EE features
3. Regenerate lock file and requirements (see below)

### 3. Generating Lock File

```bash
./backend/scripts/compile_requirements.py
```

This resolves all dependencies (core + all extras) together into a single `uv.lock` file, ensuring all versions are compatible.

### 4. Installing Dependencies

If enabled, all packages are installed automatically by the `uv-sync` pre-commit hook when changing
branches or pulling new changes.

```bash
# For everything (most common)
uv sync

# For backend production (shared + backend dependencies)
uv sync --extra backend

# For backend development (shared + backend + dev tools)
uv sync --extra backend --group dev

# For backend with EE (shared + backend + ee)
uv sync --extra backend --group ee

# For model server (shared + model_server, NO backend deps!)
uv sync --extra model_server
```

### 5. Upgrading Dependencies

Upgrade specific packages:

```bash
# Edit version in pyproject.toml, then:
./backend/scripts/compile_requirements.py
```

**Review changes carefully before committing!**

## CI/CD Integration

There is a `Validate requirements lock files` job in the [Python Checks](https://github.com/onyx-dot-app/onyx/blob/main/.github/workflows/pr-python-checks.yml)
workflow which validates the lock and requirements files are up to date.
