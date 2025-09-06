# Onyx CLI

The **Onyx CLI** provides a simple command-line interface for installing, running, and managing [Onyx](https://onyx.app) deployments.

It is designed to be:
- **Lightweight**: implemented in Python with no non-stdlib dependencies.
- **Flexible**: installs only the required deployment artifacts by default via **git sparse-checkout**.
- **Cross-platform**: runs on macOS, Linux, and Windows (WSL).

---

## Installation

The CLI is distributed as a Python package.  

### Install from PyPI
```bash
pip install onyx-cli
```
### Install from TestPyPI (for testing new releases)
```bash
pip install -i https://test.pypi.org/simple/ onyx-cli
```

Once installed, the `onyx` command is available:
```bash
onyx help
```

---

## Commands

### `onyx help`
Shows all available commands, their purpose, and key parameters.

---

### `onyx doctor`
Checks that your environment is ready for Onyx:
- Docker installed
- Docker Compose available
- Docker allocated ≥ 4 CPUs and ≥ 10 GiB RAM (required)
- Warns if RAM < 16 GiB

See our [resourcing guide](https://docs.onyx.app/deployment/getting_started/resourcing)

---

### `onyx install [--dir PATH] [--stable | --beta] [--all]`
Installs Onyx into `~/.onyx/` by default.
- Default: sparse-checkout of `deployment/` only.
- --stable: checkout the latest stable release (from Onyx Cloud API).
- --beta: checkout the latest beta release.
- --all: clone the entire repo (not just `deployment/`).

Examples:
```bash
onyx install                  # Install deployment/ from main
onyx install --stable         # Install deployment/ from latest stable release
onyx install --beta --dir ~/dev/onyx   # Install into custom dir
onyx install --all            # Clone entire repo
```

---

### `onyx up [--dir PATH] [--build-from-source] [-f COMPOSE_FILE] [-n PROJECT]`
Brings up Onyx services with Docker Compose.

- Runs `onyx doctor` first.
- Defaults to `deployment/docker_compose/docker-compose.dev.yml`.
- --build-from-source: build Docker images locally.
- -f FILE: use a specific Compose file.
- -n PROJECT: set a custom Docker project name (default: onyx-stack).

Examples:
```
onyx up
onyx up --build-from-source
onyx up -f docker-compose.prod.yml -n my-stack
```

---

### `onyx update [--dir PATH]`
Updates the Onyx repo to a new version. Interactive prompt allows you to switch to:
- Stable
- Beta
- Main branch

---

### `onyx uninstall [--dir PATH] [-n PROJECT]`
Removes Onyx installation and associated Docker resources.

---

### `onyx dev [--dir PATH]`
Sets up a development environment:
- Creates `~/.onyx/.onyx-venv`
- Installs Python requirements from `backend/requirements/`
- Installs `pre-commit` and sets it up in `backend/`
- Runs `npm install` in `web/`
- Validates Python 3.11+, Docker, and Compose are available

---

## Development

Clone the repo:
```bash
git clone https://github.com/onyx-dot-app/onyx.git
cd onyx
```

Install in editable mode:
```bash
pip install -e .
```

Run the CLI:
```bash
onyx help
```

---

## Packaging & Publishing

This project uses setuptools with `pyproject.toml`.

### 1. Build the package
Make sure you have the build tools:
```bash
pip install build twine
```

Build the distribution:
```bash
python -m build
```

This creates:
- dist/onyx_cli-X.Y.Z.tar.gz
- dist/onyx_cli-X.Y.Z-py3-none-any.whl

---

### 2. Install locally (from the built artifacts)

It’s best to test the wheel/sdist locally in a clean virtualenv before uploading anywhere.

```bash
# (Optional) create a clean env
python -m venv .venv
source .venv/bin/activate 

# Make sure build tools are present (already done if you followed step 1)
pip install --upgrade pip

# Uninstall any previously installed copy
pip uninstall -y onyx-cli || true

# Install directly from the local dist/ artifacts
# Option A: install the wheel (preferred)
pip install dist/onyx_cli-*.whl

# Option B: install from the sdist (slower; builds locally)
# pip install dist/onyx_cli-*.tar.gz

# (Optional) ensure you're really pulling only from local files
# pip install --no-index --find-links dist onyx-cli

# Smoke test
onyx help
onyx doctor --help
python -c "import cli, importlib; print('cli OK')"
```

### 3. Upload to TestPyPI (for dry runs)
Register at TestPyPI (https://test.pypi.org/).

```bash
twine upload --repository testpypi dist/*
```

Install from TestPyPI to verify:

```bash
pip install -i https://test.pypi.org/simple/ onyx-cli
onyx help
```

---

### 4. Upload to PyPI (production)
Once validated, upload to the real PyPI:

```bash
twine upload dist/*
```

Users can then install directly:

```bash
pip install onyx-cli
```

---

## Project Metadata

- License: MIT (LICENSE)
- Homepage: https://onyx.app
- Docs: https://docs.onyx.app
- Source: GitHub (https://github.com/onyx-dot-app/onyx)

---