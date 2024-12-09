<!-- DANSWER_METADATA={"link": "https://github.com/danswer-ai/danswer/blob/main/CONTRIBUTING.md"} -->

# Contributing to Danswer
Hey there! We are so excited that you're interested in Danswer.

As an open source project in a rapidly changing space, we welcome all contributions.


## 💃 Guidelines
### Contribution Opportunities
The [GitHub Issues](https://github.com/danswer-ai/danswer/issues) page is a great place to start for contribution ideas.

Issues that have been explicitly approved by the maintainers (aligned with the direction of the project)
will be marked with the `approved by maintainers` label.
Issues marked `good first issue` are an especially great place to start.

**Connectors** to other tools are another great place to contribute. For details on how, refer to this
[README.md](https://github.com/danswer-ai/danswer/blob/main/backend/danswer/connectors/README.md).

If you have a new/different contribution in mind, we'd love to hear about it!
Your input is vital to making sure that Danswer moves in the right direction.
Before starting on implementation, please raise a GitHub issue.

And always feel free to message us (Chris Weaver / Yuhong Sun) on 
[Slack](https://join.slack.com/t/danswer/shared_invite/zt-2lcmqw703-071hBuZBfNEOGUsLa5PXvQ) / 
[Discord](https://discord.gg/TDJ59cGV2X) directly about anything at all. 


### Contributing Code
To contribute to this project, please follow the
["fork and pull request"](https://docs.github.com/en/get-started/quickstart/contributing-to-projects) workflow.
When opening a pull request, mention related issues and feel free to tag relevant maintainers.

Before creating a pull request please make sure that the new changes conform to the formatting and linting requirements.
See the [Formatting and Linting](#formatting-and-linting) section for how to run these checks locally.


### Getting Help 🙋
Our goal is to make contributing as easy as possible. If you run into any issues please don't hesitate to reach out.
That way we can help future contributors and users can avoid the same issue.

We also have support channels and generally interesting discussions on our
[Slack](https://join.slack.com/t/danswer/shared_invite/zt-2afut44lv-Rw3kSWu6_OmdAXRpCv80DQ)
and 
[Discord](https://discord.gg/TDJ59cGV2X).

We would love to see you there!


## Get Started 🚀
Danswer being a fully functional app, relies on some external software, specifically:
- [Postgres](https://www.postgresql.org/) (Relational DB)
- [Vespa](https://vespa.ai/) (Vector DB/Search Engine)
- [Redis](https://redis.io/) (Cache)
- [Nginx](https://nginx.org/) (Not needed for development flows generally)


> **Note:**
> This guide provides instructions to build and run Danswer locally from source with Docker containers providing the above external software. We believe this combination is easier for
> development purposes. If you prefer to use pre-built container images, we provide instructions on running the full Danswer stack within Docker below.


### Local Set Up
Be sure to use Python version 3.11. For instructions on installing Python 3.11 on macOS, refer to the [CONTRIBUTING_MACOS.md](./CONTRIBUTING_MACOS.md) readme.

If using a lower version, modifications will have to be made to the code.
If using a higher version, sometimes some libraries will not be available (i.e. we had problems with Tensorflow in the past with higher versions of python).


#### Backend: Python requirements
Currently, we use pip and recommend creating a virtual environment.

For convenience here's a command for it:
```bash
python -m venv .venv
source .venv/bin/activate
```

> **Note:**
> This virtual environment MUST NOT be set up WITHIN the danswer directory if you plan on using mypy within certain IDEs.
> For simplicity, we recommend setting up the virtual environment outside of the danswer directory.

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
pip install -r danswer/backend/requirements/default.txt
pip install -r danswer/backend/requirements/dev.txt
pip install -r danswer/backend/requirements/ee.txt
pip install -r danswer/backend/requirements/model_server.txt
```

Install Playwright for Python (headless browser required by the Web Connector)

In the activated Python virtualenv, install Playwright for Python by running:
```bash
playwright install
```

You may have to deactivate and reactivate your virtualenv for `playwright` to appear on your path.

#### Frontend: Node dependencies

Install [Node.js and npm](https://docs.npmjs.com/downloading-and-installing-node-js-and-npm) for the frontend.
Once the above is done, navigate to `danswer/web` run:
```bash
npm i
```

#### Docker containers for external software
You will need Docker installed to run these containers.

First navigate to `danswer/deployment/docker_compose`, then start up Postgres/Vespa/Redis with:
```bash
docker compose -f docker-compose.dev.yml -p danswer-stack up -d index relational_db cache
```
(index refers to Vespa, relational_db refers to Postgres, and cache refers to Redis)


#### Running Danswer locally
To start the frontend, navigate to `danswer/web` and run:
```bash
npm run dev
```

Next, start the model server which runs the local NLP models.
Navigate to `danswer/backend` and run:
```bash
uvicorn model_server.main:app --reload --port 9000
```

_For Windows (for compatibility with both PowerShell and Command Prompt):_
```bash
powershell -Command "uvicorn model_server.main:app --reload --port 9000"
```

The first time running Danswer, you will need to run the DB migrations for Postgres.
After the first time, this is no longer required unless the DB models change.

Navigate to `danswer/backend` and with the venv active, run:
```bash
alembic upgrade head
```

Next, start the task queue which orchestrates the background jobs.
Jobs that take more time are run async from the API server.

Still in `danswer/backend`, run:
```bash
python ./scripts/dev_run_background_jobs.py
```

To run the backend API server, navigate back to `danswer/backend` and run:
```bash
AUTH_TYPE=disabled uvicorn danswer.main:app --reload --port 8080
```

_For Windows (for compatibility with both PowerShell and Command Prompt):_
```bash
powershell -Command "
    $env:AUTH_TYPE='disabled'
    uvicorn danswer.main:app --reload --port 8080 
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

Now, visit `http://localhost:3000` in your browser. You should see the Danswer onboarding wizard where you can connect your external LLM provider to Danswer.

You've successfully set up a local Danswer instance! 🏁

#### Running the Danswer application in a container

You can run the full Danswer application stack from pre-built images including all external software dependencies.

Navigate to `danswer/deployment/docker_compose` and run:

```bash
docker compose -f docker-compose.dev.yml -p danswer-stack up -d
```

After Docker pulls and starts these containers, navigate to `http://localhost:3000` to use Danswer.

If you want to make changes to Danswer and run those changes in Docker, you can also build a local version of the Danswer container images that incorporates your changes like so:

```bash
docker compose -f docker-compose.dev.yml -p danswer-stack up -d --build
```

### Formatting and Linting
#### Backend
For the backend, you'll need to setup pre-commit hooks (black / reorder-python-imports).
First, install pre-commit (if you don't have it already) following the instructions
[here](https://pre-commit.com/#installation).

With the virtual environment active, install the pre-commit library with:
```bash
pip install pre-commit
```

Then, from the `danswer/backend` directory, run:
```bash
pre-commit install
```

Additionally, we use `mypy` for static type checking.
Danswer is fully type-annotated, and we want to keep it that way! 
To run the mypy checks manually, run `python -m mypy .` from the `danswer/backend` directory.


#### Web
We use `prettier` for formatting. The desired version (2.8.8) will be installed via a `npm i` from the `danswer/web` directory. 
To run the formatter, use `npx prettier --write .` from the `danswer/web` directory.
Please double check that prettier passes before creating a pull request.


### Release Process
Danswer loosely follows the SemVer versioning standard.
Major changes are released with a "minor" version bump. Currently we use patch release versions to indicate small feature changes.
A set of Docker containers will be pushed automatically to DockerHub with every tag.
You can see the containers [here](https://hub.docker.com/search?q=danswer%2F).
