## Get Started 🚀

Onyx being a fully functional app, relies on some external software, specifically:

- [Postgres](https://www.postgresql.org/) (Relational DB)
- [Vespa](https://vespa.ai/) (Vector DB/Search Engine)
- [Redis](https://redis.io/) (Cache)
- [MinIO](https://min.io/) (File Store)
- [Nginx](https://nginx.org/) (Not needed for development flows generally)

> **Note:**
> This guide provides instructions to build and run Onyx locally from source with Docker containers providing the above external software. We believe this combination is easier for
> development purposes. If you prefer to use pre-built container images, we provide instructions on running the full Onyx stack within Docker below.

### Local Set Up

Be sure to use Python version 3.11. For instructions on installing Python 3.11 on macOS, refer to the [contributing_macos.md](./contributing_macos.md) readme.

If using a lower version, modifications will have to be made to the code.
If using a higher version, sometimes some libraries will not be available (i.e. we had problems with Tensorflow in the past with higher versions of python).

#### Backend: Python requirements

Currently, we use [uv](https://docs.astral.sh/uv/) and recommend creating a [virtual environment](https://docs.astral.sh/uv/pip/environments/#using-a-virtual-environment).

For convenience here's a command for it:

```bash
uv venv .venv --python 3.11
source .venv/bin/activate
```

_For Windows, activate the virtual environment using Command Prompt:_

```bash
.venv\Scripts\activate
```

If using PowerShell, the command slightly differs:

```powershell
.venv\Scripts\Activate.ps1
```

Install the required python dependencies:

```bash
uv sync --all-extras
```

Install Playwright for Python (headless browser required by the Web Connector):

```bash
uv run playwright install
```

#### Frontend: Node dependencies

Onyx uses Node v22.20.0. We highly recommend you use [Node Version Manager (nvm)](https://github.com/nvm-sh/nvm)
to manage your Node installations. Once installed, you can run

```bash
nvm install 22 && nvm use 22
node -v # verify your active version
```

Navigate to `onyx/web` and run:

```bash
npm i
```

## Formatting and Linting

### Backend

For the backend, you'll need to setup pre-commit hooks (black / reorder-python-imports).

Then run:

```bash
uv run pre-commit install
```

Additionally, we use `mypy` for static type checking.
Onyx is fully type-annotated, and we want to keep it that way!
To run the mypy checks manually, run `uv run mypy .` from the `onyx/backend` directory.

### Web

We use `prettier` for formatting. The desired version will be installed via a `npm i` from the `onyx/web` directory.
To run the formatter, use `npx prettier --write .` from the `onyx/web` directory.

Pre-commit will also run prettier automatically on files you've recently touched. If re-formatted, your commit will fail.
Re-stage your changes and commit again.

# Running the application for development

## Developing using VSCode Debugger (recommended)

**We highly recommend using VSCode debugger for development.**
See [contributing_vscode.md](./contributing_vscode.md) for more details.

Otherwise, you can follow the instructions below to run the application for development.

## Manually running the application for development
### Docker containers for external software

You will need Docker installed to run these containers.

First navigate to `onyx/deployment/docker_compose`, then start up Postgres/Vespa/Redis/MinIO with:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d index relational_db cache minio
```

(index refers to Vespa, relational_db refers to Postgres, and cache refers to Redis)

### Running Onyx locally

To start the frontend, navigate to `onyx/web` and run:

```bash
npm run dev
```

Next, start the model server which runs the local NLP models.
Navigate to `onyx/backend` and run:

```bash
uvicorn model_server.main:app --reload --port 9000
```

_For Windows (for compatibility with both PowerShell and Command Prompt):_

```bash
powershell -Command "uvicorn model_server.main:app --reload --port 9000"
```

The first time running Onyx, you will need to run the DB migrations for Postgres.
After the first time, this is no longer required unless the DB models change.

Navigate to `onyx/backend` and with the venv active, run:

```bash
alembic upgrade head
```

Next, start the task queue which orchestrates the background jobs.
Jobs that take more time are run async from the API server.

Still in `onyx/backend`, run:

```bash
python ./scripts/dev_run_background_jobs.py
```

To run the backend API server, navigate back to `onyx/backend` and run:

```bash
AUTH_TYPE=disabled uvicorn onyx.main:app --reload --port 8080
```

_For Windows (for compatibility with both PowerShell and Command Prompt):_

```bash
powershell -Command "
    $env:AUTH_TYPE='disabled'
    uvicorn onyx.main:app --reload --port 8080
"
```

> **Note:**
> If you need finer logging, add the additional environment variable `LOG_LEVEL=DEBUG` to the relevant services.

#### Wrapping up

You should now have 4 servers running:

- Web server
- Backend API
- Model server
- Background jobs

Now, visit `http://localhost:3000` in your browser. You should see the Onyx onboarding wizard where you can connect your external LLM provider to Onyx.

You've successfully set up a local Onyx instance! 🏁

#### Running the Onyx application in a container

You can run the full Onyx application stack from pre-built images including all external software dependencies.

Navigate to `onyx/deployment/docker_compose` and run:

```bash
docker compose up -d
```

After Docker pulls and starts these containers, navigate to `http://localhost:3000` to use Onyx.

If you want to make changes to Onyx and run those changes in Docker, you can also build a local version of the Onyx container images that incorporates your changes like so:

```bash
docker compose up -d --build
```
