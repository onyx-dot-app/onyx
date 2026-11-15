# Integration Tests

## General Testing Overview

The integration tests are designed with a "manager" class and a "test" class for each type of object being manipulated (e.g., user, persona, credential):

- **Manager Class**: Contains methods for each type of API call. Responsible for creating, deleting, and verifying the existence of an entity.
- **Test Class**: Stores data for each entity being tested. This is our "expected state" of the object.

The idea is that each test can use the manager class to create (.create()) a "test*" object. It can then perform an operation on the object (e.g., send a request to the API) and then check if the "test*" object is in the expected state by using the manager class (.verify()) function.

Craft Kubernetes tests under `tests/integration/tests/craft/k8s/` run in the
dedicated `pr-craft-k8s-tests.yml` lane against a Helm-installed kind cluster
with the real api_server, web_server, Celery workers, sandbox-proxy, and sandbox
pods. Prefer the same API-manager shape there for API behavior. Use direct
sandbox manager calls only for low-level Kubernetes contracts that are not
exposed cleanly through public APIs; direct task/stub checks belong in
`tests/external_dependency_unit/craft/`.

## Instructions for Running Integration Tests Locally

The tests call the API through the manager classes in `common_utils/managers`, so
the generated OpenAPI client is not needed. Use `ods openapi all` only if you want
the schema or client for other work.

1. Start the services Onyx depends on (for example with Docker). The test session runs the api_server in-process through
   `TestClient` and starts the Celery workers itself, so do not start those.
   - If you'd like to set environment variables, you can do so by creating a `.env` file in the onyx/backend/tests/integration/ directory.
   - Onyx MUST be configured with AUTH_TYPE=basic.
   - Enterprise tests run only with `RUN_EE_TESTS=true`. They also need a license: put it in `ONYX_DEV_LICENSE`
     and the session seeds it.
2. Navigate to `onyx/backend`.
3. Run the following command in the terminal:
   ```sh
   python -m dotenv -f .env run -- pytest -s tests/integration/tests/
   ```
   or to run all tests in a file:
   ```sh
   python -m dotenv -f .env run -- pytest -s tests/integration/tests/path_to/test_file.py
   ```
   or to run a single test:
   ```sh
   python -m dotenv -f .env run -- pytest -s tests/integration/tests/path_to/test_file.py::test_function_name
   ```

Running some single tests require the `mock_connector_server` container to be running. If the above doesn't work, 
navigate to `backend/tests/integration/mock_services` and run
```sh
docker compose -f docker-compose.mock-it-services.yml -p mock-it-services-stack up -d
```
You will have to modify the networks section of the docker-compose file to `<your stack name>_default` if you brought up the standard
onyx services with a name different from the default `onyx`.

## Guidelines for Writing Integration Tests

- As authentication is currently required for all tests, each test should start by creating a user.
- Each test should ideally focus on a single API flow.
- The test writer should try to consider failure cases and edge cases for the flow and write the tests to check for these cases.
- Every step of the test should be commented describing what is being done and what the expected behavior is.
- A summary of the test should be given at the top of the test function as well!
- When writing new tests, manager classes, manager functions, and test classes, try to copy the style of the other ones that have already been written.
- Be careful for scope creep!
  - No need to overcomplicate every test by verifying after every single API call so long as the case you would be verifying is covered elsewhere (ideally in a test focused on covering that case).
  - An example of this is: Creating an admin user is done at the beginning of nearly every test, but we only need to verify that the user is actually an admin in the test focused on checking admin permissions. For every other test, we can just create the admin user and assume that the permissions are working as expected.

## Scripting the LLM with `mock_llm`

The `mock_llm` fixture (from `tests/integration/conftest.py`) fakes the LLM provider. The session starts a scripted
OpenAI-compatible server (`tests/integration/mock_services/mock_llm_server/server.py`) in a thread. For each test,
the fixture makes a new script and an `openai_compatible` provider (model `mock-model`) that points at it, and sets
that provider as the default. Requests go through the real provider layer (LiteLLM, streaming, retries).

The fixture yields a `MockLLMScript`. Tell the model what to say with conversations of replies:

```python
from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    ToolCall,
)


def test_search_then_answer(admin_user: DATestUser, mock_llm: MockLLMScript) -> None:
    mock_llm.conversation(
        "chat",
        Reply(
            tool_calls=[
                ToolCall(
                    id="call_1", name="internal_search", arguments={"queries": ["pto"]}
                )
            ],
            conditions=RequestConditions(offers=["internal_search"]),
        ),
        Reply(
            text="Twenty days.",
            conditions=RequestConditions(has_results_for=["call_1"]),
        ),
    )
    response = ChatSessionManager.send_message(...)
    first, second = mock_llm.requests_in("chat")
    assert second.tool_result("call_1") is not None
```

- **Reply**: one response with optional `reasoning`, `text`, and `tool_calls`. The finish reason is `tool_calls` when
  there are tool calls, else `stop`. `required=False` lets the reply stay unused.
- **Conversation**: a name, `conditions`, and ordered replies. A request goes to the next unused reply of each
  conversation whose request conditions (and the reply's own) it meets. Use one conversation per independent flow, for
  example one per parallel Deep Research agent. Put an optional reply in its own conversation.
- **RequestConditions**: every set field must hold: `has_tools`, `offers`, `does_not_offer`, `has_results_for` (tool call ids with
  a result in the history), `tool_choice` (`auto`, `required`, or `none`), and `prompt_contains` (system and user text
  only; use it as a last resort).
- **Tool-free requests**: a request with no tools and no tool results (for example query rephrase, section selection,
  or session naming) goes only to a reply whose conversation or reply conditions set `has_tools=False`.
- **Default reply**: a request that no reply accepts gets `Script.default_reply` (default text
  `This is a mock LLM response.`). The default reply is never used up. With `Script(default_reply=None)` such a
  request gets HTTP 400, and Onyx does not retry it.
- When replies from two conversations accept a request with different responses, the server rejects it as ambiguous.
- **Recorded requests**: `mock_llm.requests` lists every request (`messages`, `tools`, `tool_choice`, `body`) and what
  served it (`conversation`, `reply_index`, `used_default_reply`, `error`). Use `requests_in(name)` and
  `tool_result(call_id)`.
- At teardown the fixture restores the previous default provider, deletes the mock provider, and fails the test if a
  request got an error or a required reply was not used.
- `StreamedResponse.packets` holds every placed packet as `{"placement": {...}, "obj": {...}}`.

See `tests/llm_workflows/test_mock_llm_server.py`. Tests that must patch Onyx or control the stream very finely
belong in `tests/external_dependency_unit/` with `MockLLM`.

The Playwright stack runs the same server as a compose service
(`deployment/docker_compose/docker-compose.mock-llm-test.yml`). See `web/tests/e2e/README.md`.

## Current Testing Limitations

### Test coverage

- All tests are probably not as high coverage as they could be.
- The "connector" tests in particular are super bare bones because we will be reworking connector/cc_pair sometime soon.
- Global Curator role is not thoroughly tested.
- No auth is not tested at all.

### Failure checking

- While we test expected auth failures, we only check that it failed at all.
- We dont check that the return codes are what we expect.
- This means that a test could be failing for a different reason than expected.
- We should ensure that the proper codes are being returned for each failure case.
- We should also query the db after each failure to ensure that the db is in the expected state.

### Scope/focus

- The tests may be scoped sub-optimally.
- The scoping of each test may be overlapping.

## Current Testing Coverage

The current testing coverage should be checked by reading the comments at the top of each test file.

## TODO: Testing Coverage

- Persona permissions testing
- Read only (and/or basic) user permissions
  - Ensuring proper permission enforcement using the chat/doc_search endpoints
- No auth

## Ideas for integration testing design

### Combine the "test" and "manager" classes

This could make test writing a bit cleaner by preventing test writers from having to pass around objects into functions that the objects have a 1:1 relationship with.

### Rework DocumentIndexClient

Right now, its used a fixture and has to be passed around between manager classes.
Could just be built where its used
