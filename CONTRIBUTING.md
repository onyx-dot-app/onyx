# Contributing to Onyx

Hey there! We are so excited that you're interested in Onyx.

## Table of Contents

- [Contribution Opportunities](#contribution-opportunities)
- [Contribution Process](#contribution-process)
- [Development Setup](#development-setup)
  - [Prerequisites](#prerequisites)
  - [Backend: Python Requirements](#backend-python-requirements)
  - [Frontend: Node Dependencies](#frontend-node-dependencies)
  - [Formatting and Linting](#formatting-and-linting)
- [Running the Application](#running-the-application)
  - [VSCode Debugger (Recommended)](#vscode-debugger-recommended)
  - [Manually Running for Development](#manually-running-for-development)
  - [Running in Docker](#running-in-docker)
- [macOS-Specific Notes](#macos-specific-notes)
- [Engineering Best Practices](#engineering-best-practices)
  - [Principles and Collaboration](#principles-and-collaboration)
  - [Style and Maintainability](#style-and-maintainability)
  - [Performance and Correctness](#performance-and-correctness)
  - [Repository Conventions](#repository-conventions)
- [Release Process](#release-process)
- [Getting Help](#getting-help)
- [Enterprise Edition Contributions](#enterprise-edition-contributions)

---

## Contribution Opportunities

The [GitHub Issues](https://github.com/onyx-dot-app/onyx/issues) page is a great place to look for and share contribution ideas.

If you have your own feature that you would like to build, please create an issue and community members can provide feedback and upvote if they feel a common need.

---

## Contribution Process

To contribute, please follow the
["fork and pull request"](https://docs.github.com/en/get-started/quickstart/contributing-to-projects) workflow.

### 1. Get the feature or enhancement approved

Create a GitHub issue and see if there are upvotes. If you feel the feature is sufficiently value-additive and you would like approval to contribute it to the repo, tag [Yuhong](https://github.com/yuhongsun96) to review.

If you do not get a response within a week, feel free to email yuhong@onyx.app and include the issue in the message.

Not all small features and enhancements will be accepted as there is a balance between feature richness and bloat. We strive to provide the best user experience possible so we have to be intentional about what we include in the app.

### 2. Get the design approved

The Onyx team will either provide a design doc and PRD for the feature or request one from you, the contributor. The scope and detail of the design will depend on the individual feature.

### 3. IP attribution for EE contributions

If you are contributing features to Onyx Enterprise Edition, you are required to sign the [IP Assignment Agreement](contributing_guides/EE_Contributor_IP_Assignment_Agreement.md).

### 4. Review and testing

Your features must pass all tests and all comments must be addressed prior to merging.

### Implicit agreements

If we approve an issue, we are promising you the following:
- Your work will receive timely attention and we will put aside other important items to ensure you are not blocked.
- You will receive necessary coaching on eng quality, system design, etc. to ensure the feature is completed well.
- The Onyx team will pull resources and bandwidth from design, PM, and engineering to ensure that you have all the resources to build the feature to the quality required for merging.

Because this is a large investment from our team, we ask that you:
- Thoroughly read all the requirements of the design docs, engineering best practices, and try to minimize overhead for the Onyx team.
- Complete the feature in a timely manner to reduce context switching and an ongoing resource pull from the Onyx team.

---

## Development Setup

Onyx being a fully functional app, relies on some external software, specifically:

- [Postgres](https://www.postgresql.org/) (Relational DB)
- [OpenSearch](https://opensearch.org/) (Vector DB/Search Engine)
- [Redis](https://redis.io/) (Cache)
- [MinIO](https://min.io/) (File Store)
- [Nginx](https://nginx.org/) (Not needed for development flows generally)

> **Note:**
> This guide provides instructions to build and run Onyx locally from source with Docker containers providing the above external software.
> We believe this combination is easier for development purposes. If you prefer to use pre-built container images, see [Running in Docker](#running-in-docker) below.

### Prerequisites

- **Python 3.11** — If using a lower version, modifications will have to be made to the code. Higher versions may have library compatibility issues.
- **Docker** — Required for running external services (Postgres, OpenSearch, Redis, MinIO).
- **Node.js v22** — We recommend using [nvm](https://github.com/nvm-sh/nvm) to manage Node installations.

### Backend: Python Requirements

We use [uv](https://docs.astral.sh/uv/) and recommend creating a [virtual environment](https://docs.astral.sh/uv/pip/environments/#using-a-virtual-environment).

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

Install the required Python dependencies:

```bash
uv sync --all-extras
```

Install Playwright for Python (headless browser required by the Web Connector):

```bash
uv run playwright install
```

### Frontend: Node Dependencies

```bash
nvm install 22 && nvm use 22
node -v # verify your active version
```

Navigate to `onyx/web` and run:

```bash
npm i
```

### Formatting and Linting

#### Backend

Set up pre-commit hooks (black / reorder-python-imports):

```bash
uv run pre-commit install
```

We also use `mypy` for static type checking. Onyx is fully type-annotated, and we want to keep it that way! To run the mypy checks manually:

```bash
uv run mypy .  # from onyx/backend
```

#### Frontend

We use `prettier` for formatting. The desired version will be installed via `npm i` from the `onyx/web` directory. To run the formatter:

```bash
npx prettier --write .  # from onyx/web
```

Pre-commit will also run prettier automatically on files you've recently touched. If re-formatted, your commit will fail. Re-stage your changes and commit again.

---

## Running the Application

### VSCode Debugger (Recommended)

We highly recommend using VSCode's debugger for development.

#### Initial Setup

1. Copy `.vscode/env_template.txt` to `.vscode/.env`
2. Fill in the necessary environment variables in `.vscode/.env`

#### Using the Debugger

Before starting, make sure the Docker Daemon is running.

1. Open the Debug view in VSCode (Cmd+Shift+D on macOS)
2. From the dropdown at the top, select "Clear and Restart External Volumes and Containers" and press the green play button
3. From the dropdown at the top, select "Run All Onyx Services" and press the green play button
4. Navigate to http://localhost:3000 in your browser to start using the app
5. Set breakpoints by clicking to the left of line numbers to help debug while the app is running
6. Use the debug toolbar to step through code, inspect variables, etc.

> **Note:** "Clear and Restart External Volumes and Containers" will reset your Postgres and OpenSearch (relational-db and index). Only run this if you are okay with wiping your data.

**Features:**
- Hot reload is enabled for the web server and API servers
- Python debugging is configured with debugpy
- Environment variables are loaded from `.vscode/.env`
- Console output is organized in the integrated terminal with labeled tabs

### Manually Running for Development

#### Docker containers for external software

You will need Docker installed to run these containers.

Navigate to `onyx/deployment/docker_compose`, then start up Postgres/OpenSearch/Redis/MinIO with:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d index relational_db cache minio
```

(index refers to OpenSearch, relational_db refers to Postgres, and cache refers to Redis)

#### Running Onyx locally

To start the frontend, navigate to `onyx/web` and run:

```bash
npm run dev
```

Next, start the model server which runs the local NLP models. Navigate to `onyx/backend` and run:

```bash
uvicorn model_server.main:app --reload --port 9000
```

_For Windows (for compatibility with both PowerShell and Command Prompt):_

```bash
powershell -Command "uvicorn model_server.main:app --reload --port 9000"
```

The first time running Onyx, you will need to run the DB migrations for Postgres. After the first time, this is no longer required unless the DB models change.

Navigate to `onyx/backend` and with the venv active, run:

```bash
alembic upgrade head
```

Next, start the task queue which orchestrates the background jobs. Still in `onyx/backend`, run:

```bash
python ./scripts/dev_run_background_jobs.py
```

To run the backend API server, navigate back to `onyx/backend` and run:

```bash
AUTH_TYPE=basic uvicorn onyx.main:app --reload --port 8080
```

_For Windows (for compatibility with both PowerShell and Command Prompt):_

```bash
powershell -Command "
    $env:AUTH_TYPE='basic'
    uvicorn onyx.main:app --reload --port 8080
"
```

> **Note:** If you need finer logging, add the additional environment variable `LOG_LEVEL=DEBUG` to the relevant services.

#### Wrapping up

You should now have 4 servers running:

- Web server
- Backend API
- Model server
- Background jobs

Now, visit http://localhost:3000 in your browser. You should see the Onyx onboarding wizard where you can connect your external LLM provider to Onyx.

You've successfully set up a local Onyx instance!

### Running in Docker

You can run the full Onyx application stack from pre-built images including all external software dependencies.

Navigate to `onyx/deployment/docker_compose` and run:

```bash
docker compose up -d
```

After Docker pulls and starts these containers, navigate to http://localhost:3000 to use Onyx.

If you want to make changes to Onyx and run those changes in Docker, you can also build a local version of the Onyx container images that incorporates your changes:

```bash
docker compose up -d --build
```

---

## macOS-Specific Notes

### Setting up Python

Ensure [Homebrew](https://brew.sh/) is already set up, then install Python 3.11:

```bash
brew install python@3.11
```

Add Python 3.11 to your path by adding the following line to `~/.zshrc`:

```
export PATH="$(brew --prefix)/opt/python@3.11/libexec/bin:$PATH"
```

> **Note:** You will need to open a new terminal for the path change above to take effect.

### Setting up Docker

On macOS, you will need to install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and ensure it is running before continuing with the docker commands.

### Formatting and Linting

macOS will likely require you to remove some quarantine attributes on some of the hooks for them to execute properly. After installing pre-commit, run the following command:

```bash
sudo xattr -r -d com.apple.quarantine ~/.cache/pre-commit
```

---

## Engineering Best Practices

> These are also what we adhere to as a team internally, we love to build in the open and to uplevel our community and each other through being transparent.

### Principles and Collaboration

- **Use 1-way vs 2-way doors.** For 2-way doors, move faster and iterate. For 1-way doors, be more deliberate.
- **Consistency > being "right."** Prefer consistent patterns across the codebase. If something is truly bad, fix it everywhere.
- **Fix what you touch (selectively).**
  - Don't feel obligated to fix every best-practice issue you notice.
  - Don't introduce new bad practices.
  - If your change touches code that violates best practices, fix it as part of the change.
- **Don't tack features on.** When adding functionality, restructure logically as needed to avoid muddying interfaces and accumulating tech debt.

### Style and Maintainability

#### Comments and readability
Add clear comments:
- At logical boundaries (e.g., interfaces) so the reader doesn't need to dig 10 layers deeper.
- Wherever assumptions are made or something non-obvious/unexpected is done.
- For complicated flows/functions.
- Wherever it saves time (e.g., nontrivial regex patterns).

#### Errors and exceptions
- **Fail loudly** rather than silently skipping work.
  - Example: raise and let exceptions propagate instead of silently dropping a document.
- **Don't overuse `try/except`.**
  - Put `try/except` at the correct logical level.
  - Do not mask exceptions unless it is clearly appropriate.

#### Typing
- Everything should be **as strictly typed as possible**.
- Use `cast` for annoying/loose-typed interfaces (e.g., results of `run_functions_tuples_in_parallel`).
  - Only `cast` when the type checker sees `Any` or types are too loose.
- Prefer types that are easy to read.
  - Avoid dense types like `dict[tuple[str, str], list[list[float]]]`.
  - Prefer domain models, e.g.:
    - `EmbeddingModel(provider_name, model_name)` as a Pydantic model
    - `dict[EmbeddingModel, list[EmbeddingVector]]`

#### State, objects, and boundaries
- Keep **clear logical boundaries** for state containers and objects.
- A **config** object should never contain things like a `db_session`.
- Avoid state containers that are overly nested, or huge + flat (use judgment).
- Prefer **composition and functional style** over inheritance/OOP.
- Prefer **no mutation** unless there's a strong reason.
- State objects should be **intentional and explicit**, ideally nonmutating.
- Use interfaces/objects to create clear separation of responsibility.
- Prefer simplicity when there's no clear gain.
  - Avoid overcomplicated mechanisms like semaphores.
  - Prefer **hash maps (dicts)** over tree structures unless there's a strong reason.

#### Naming
- Name variables carefully and intentionally.
- Prefer long, explicit names when undecided.
- Avoid single-character variables except for small, self-contained utilities (or not at all).
- Keep the same object/name consistent through the call stack and within functions when reasonable.
  - Good: `for token in tokens:`
  - Bad: `for msg in tokens:` (if iterating tokens)
- Function names should bias toward **long + descriptive** for codebase search.
  - IntelliSense can miss call sites; search works best with unique names.

#### Correctness by construction
- Prefer self-contained correctness — don't rely on callers to "use it right" if you can make misuse hard.
- Avoid redundancies: if a function takes an arg, it shouldn't also take a state object that contains that same arg.
- No dead code (unless there's a very good reason).
- No commented-out code in main or feature branches (unless there's a very good reason).
- No duplicate logic:
  - Don't copy/paste into branches when shared logic can live above the conditional.
  - If you're afraid to touch the original, you don't understand it well enough.
  - LLMs often create subtle duplicate logic — review carefully and remove it.
  - Avoid "nearly identical" objects that confuse when to use which.
- Avoid extremely long functions with chained logic:
  - Encapsulate steps into helpers for readability, even if not reused.
  - "Pythonic" multi-step expressions are OK in moderation; don't trade clarity for cleverness.

### Performance and Correctness

- Avoid holding resources for extended periods (DB sessions, locks/semaphores).
- Validate objects on creation and right before use.
- Connector code (data to Onyx documents):
  - Any in-memory structure that can grow without bound based on input must be periodically size-checked.
  - If a connector is OOMing (often shows up as "missing celery tasks"), this is a top thing to check retroactively.
- Async and event loops:
  - Never introduce new async/event loop Python code, and try to make existing async code synchronous when possible if it makes sense.
  - Writing async code without 100% understanding the code and having a concrete reason to do so is likely to introduce bugs and not add any meaningful performance gains.

### Repository Conventions

#### Where code lives
- Pydantic + data models: `models.py` files.
- DB interface functions (excluding lazy loading): `db/` directory.
- LLM prompts: `prompts/` directory, roughly mirroring the code layout that uses them.
- API routes: `server/` directory.

#### Pydantic and modeling
- Prefer **Pydantic** over dataclasses.
- If absolutely required, use `allow_arbitrary_types`.

#### Data conventions
- Prefer explicit `None` over sentinel empty strings (usually; depends on intent).
- Prefer explicit identifiers: use string enums instead of integer codes.
- Avoid magic numbers (co-location is good when necessary). **Always avoid magic strings.**

#### Logging
- Log messages where they are created.
- Don't propagate log messages around just to log them elsewhere.

#### Encapsulation
- Don't use private attributes/methods/properties from other classes/modules.
- "Private" is private — respect that boundary.

#### SQLAlchemy guidance
- Lazy loading is often bad at scale, especially across multiple list relationships.
- Be careful when accessing SQLAlchemy object attributes:
  - It can help avoid redundant DB queries,
  - but it can also fail if accessed outside an active session,
  - and lazy loading can add hidden DB dependencies to otherwise "simple" functions.
- Reference: https://www.reddit.com/r/SQLAlchemy/comments/138f248/joinedload_vs_selectinload/

#### Trunk-based development and feature flags
- **PRs should contain no more than 500 lines of real change.**
- **Merge to main frequently.** Avoid long-lived feature branches — they create merge conflicts and integration pain.
- **Use feature flags for incremental rollout.**
  - Large features should be merged in small, shippable increments behind a flag.
  - This allows continuous integration without exposing incomplete functionality.
- **Keep flags short-lived.** Once a feature is fully rolled out, remove the flag and dead code paths promptly.
- **Flag at the right level.** Prefer flagging at API/UI entry points rather than deep in business logic.
- **Test both flag states.** Ensure the codebase works correctly with the flag on and off.

#### Miscellaneous
- Any TODOs you add in the code must be accompanied by either the name/username of the owner of that TODO, or an issue number for an issue referencing that piece of work.
- Avoid module-level logic that runs on import, which leads to import-time side effects. Essentially every piece of meaningful logic should exist within some function that has to be explicitly invoked. Acceptable exceptions may include loading environment variables or setting up loggers.
  - If you find yourself needing something like this, you may want that logic to exist in a file dedicated for manual execution (contains `if __name__ == "__main__":`) which should not be imported by anything else.
- Do not conflate Python scripts you intend to run from the command line (contains `if __name__ == "__main__":`) with modules you intend to import from elsewhere. If for some unlikely reason they have to be the same file, any logic specific to executing the file (including imports) should be contained in the `if __name__ == "__main__":` block.
  - Generally these executable files exist in `backend/scripts/`.

---

## Release Process

Onyx loosely follows the SemVer versioning standard.
Major changes are released with a "minor" version bump. Currently we use patch release versions to indicate small feature changes.
A set of Docker containers will be pushed automatically to DockerHub with every tag.
You can see the containers [here](https://hub.docker.com/search?q=onyx%2F).

---

## Getting Help

We have support channels and generally interesting discussions on our [Discord](https://discord.gg/4NA5SbzrWb).

See you there!

---

## Enterprise Edition Contributions

If you are contributing features to Onyx Enterprise Edition (code under any `ee/` directory), you are required to sign the [IP Assignment Agreement](contributing_guides/EE_Contributor_IP_Assignment_Agreement.md) ([PDF version](contributing_guides/EE_Contributor_IP_Assignment_Agreement.pdf)).
