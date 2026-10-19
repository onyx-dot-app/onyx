# Validate the development stack

Run these tests on a development host with Docker, uv, Bun, and Go installed.
Use two disposable Onyx worktrees. Do not use deployments with important data or external credentials.
The tests create local accounts, stop services, change ports, and recreate containers.

Build ODS from the branch under test:

```sh
ODS_STACK_BUILD_DIR="$(mktemp -d "$(git rev-parse --path-format=absolute --git-path ods-stack-validation).XXXXXX")"
export ODS_STACK_LIVE_BINARY="$ODS_STACK_BUILD_DIR/ods"
go -C tools/ods build -o "$ODS_STACK_LIVE_BINARY" .
```

Set both worktree paths and run the live lifecycle test:

```sh
export ODS_STACK_LIVE_ROOT_A=/absolute/path/to/worktree-a
export ODS_STACK_LIVE_ROOT_B=/absolute/path/to/worktree-b
cd "$(git rev-parse --show-toplevel)/tools/ods"
go test -tags integration ./integration -run TestStackLiveLifecycle -count=1 -timeout 90m -v
```

The harness explicitly uses the global `--isolated` option. The test checks distinct projects and ports, database isolation, concurrent startup, process reuse,
stop and start, occupied-port recovery, and data preservation after container recreation.
Unset configuration skips the test, so the normal unit suite does not start Docker.

The test runs `stack down` during cleanup. Docker volumes and durable port leases remain.
Set `ODS_STACK_KEEP_RUNNING=1` to leave the stacks available for browser tests.
Get the current frontend URL with `"$ODS_STACK_LIVE_BINARY" --isolated stack status --json` in each worktree.
Never assume port 3000 after the occupied-port test.

Run browser tests only after the lifecycle test finishes.
Follow [the browser test instructions](../../../web/tests/e2e/README.md) to start the mock LLM server and install Playwright's browsers.
Set `BASE_URL` to the disposable stack's frontend URL.
Set `MOCK_LLM_SERVER_URL` and `MOCK_LLM_BACKEND_URL` to the test server's reachable address.

```sh
cd "$(git rev-parse --show-toplevel)/web"
bun run playwright --config playwright.stack.config.ts
```

This configuration runs login, signup, welcome-page, and chat-persistence checks without paid-license setup.
Its setup creates the test admin and sets the display name.
When `MOCK_LLM_SERVER_URL` is set, setup also makes the scripted mock LLM the default provider.
Use the mock provider for an enabled chat input and the real backend chat-persistence check.
Do not run two browser commands with this configuration concurrently; they share an output directory.

After browser tests, validate real Celery processing with the default profile:

```sh
cd "$(git rev-parse --show-toplevel)/tools/ods"
ODS_STACK_LIVE_WORKERS=1 go test -tags integration ./integration -run TestStackLiveUserFileWorker -count=1 -timeout 30m -v
```

Keep the three `ODS_STACK_LIVE_*` path variables from the lifecycle test.
The worker test uploads a small text file and waits for indexed chunks without mocked status responses.
The first embedding request can download model weights and take several minutes.
Cleanup requests file deletion. The test does not assert that asynchronous deletion finishes.

After browser tests, run `"$ODS_STACK_LIVE_BINARY" --isolated stack down` in both worktrees.
Stop only the mock LLM server that you started for this run.
Do not prune shared Docker volumes or stop other worktrees.
