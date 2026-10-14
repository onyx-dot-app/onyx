# Validate the development stack

Run these tests on a development host with Docker, uv, Bun, and Go installed.
Use two disposable Onyx worktrees. Do not use deployments with important data or external credentials.
The tests create local accounts, stop services, change ports, and recreate containers.

Build ODS from the branch under test:

```sh
go -C tools/ods build -o /tmp/ods-stack-validation .
```

Set both worktree paths and run the live lifecycle test:

```sh
export ODS_STACK_LIVE_BINARY=/tmp/ods-stack-validation
export ODS_STACK_LIVE_ROOT_A=/absolute/path/to/worktree-a
export ODS_STACK_LIVE_ROOT_B=/absolute/path/to/worktree-b
cd tools/ods
go test -tags integration ./integration -run TestStackLiveLifecycle -count=1 -timeout 90m -v
```

The test checks distinct projects and ports, database isolation, concurrent startup, process reuse,
stop and start, occupied-port recovery, and data preservation after container recreation.
Unset configuration skips the test, so the normal unit suite does not start Docker.

The test runs `stack down` during cleanup. Docker volumes and durable port leases remain.
Set `ODS_STACK_KEEP_RUNNING=1` to leave the stacks available for browser tests.
Get the current frontend URL with `ods stack status --json` in each worktree.
Never assume port 3000 after the occupied-port test.

Run browser tests only after the lifecycle test finishes.
Follow [the browser test instructions](../../../web/tests/e2e/README.md) for the mock LLM server and Playwright.
Point `BASE_URL` at the disposable stack's frontend URL.
Set `MOCK_LLM_SERVER_URL` and `MOCK_LLM_BACKEND_URL` to the test server's reachable address.
Global setup creates test users and changes the default LLM provider in that deployment.

After browser tests, run `ods stack down` in both worktrees.
Stop only the mock LLM server that you started for this run.
Do not prune shared Docker volumes or stop other worktrees.
