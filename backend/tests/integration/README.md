# Integration Tests

## General Testing Overview

The integration tests are designed with a "manager" class and a "test" class for each type of object being manipulated (e.g., user, persona, credential):

- **Manager Class**: Contains methods for each type of API call. Responsible for creating, deleting, and verifying the existence of an entity.
- **Test Class**: Stores data for each entity being tested. This is our "expected state" of the object.

The idea is that each test can use the manager class to create (.create()) a "test*" object. It can then perform an operation on the object (e.g., send a request to the API) and then check if the "test*" object is in the expected state by using the manager class (.verify()) function.

## Instructions for Running Integration Tests Locally

1. Launch onyx (using Docker or running with a debugger), ensuring the API server is running on port 8080.
   - If you'd like to set environment variables, you can do so by creating a `.env` file in the onyx/backend/tests/integration/ directory.
   - Onyx MUST be launched with AUTH_TYPE=basic and ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=true
2. Navigate to `onyx/backend`.
3. Run the following command in the terminal:
   ```sh
   pytest -s tests/integration/tests/
   ```
   or to run all tests in a file:
   ```sh
   pytest -s tests/integration/tests/path_to/test_file.py
   ```
   or to run a single test:
   ```sh
   pytest -s tests/integration/tests/path_to/test_file.py::test_function_name
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

### Rework VespaClient

Right now, its used a fixture and has to be passed around between manager classes.
Could just be built where its used
