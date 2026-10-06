# Generated PR tasks

Use `reusable-agent-task-pr.yml` for a task that changes approved repository files
and opens a reviewed PR. It handles bot authentication, concurrency, repair guards,
fallback execution, PR publishing, and Slack review messages.

The caller selects the execution adapter. Python tasks keep their existing
`--write --rationale-file` contract. Coding harness tasks use a trusted prompt
and a separate validation script.

## Python tasks and the Responses API

`task-runner: script` is the default. The recommended-model job uses this adapter.
Its Python script builds the prompt, calls `backend/scripts/openai_agent.py`,
validates the returned data, and writes the output files.

```yaml
jobs:
  update:
    uses: ./.github/workflows/reusable-agent-task-pr.yml
    secrets:
      CHERRY_PICK_APP_PRIVATE_KEY: ${{ secrets.CHERRY_PICK_APP_PRIVATE_KEY }}
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    with:
      task-name: recommended-models
      script: backend/scripts/update_recommended_models_agent.py
      files: backend/onyx/llm/well_known_providers/recommended-models.json
      branch: auto/update-recommended-models
      pr-title: "chore(llms): update recommended models"
      reviewer: rohoswagger
```

## Coding harness tasks

Select `task-runner: claude-code` and pass `ANTHROPIC_API_KEY`.
Set `prompt-file`, `files`, and `validation-script`. Paths are relative to the
task checkout. Keep both the prompt and validator outside the approved output paths.

The runner copies the checkout into a temporary directory. Claude can read and
edit that copy. After a successful run, the runner transfers only approved regular
files and deletions into the publishing checkout. It rejects symlinks, new executable
files, changes to executable permissions, absolute paths, traversal, and Git metadata paths.
The agent must also write a nonempty rationale for the PR body.

The workflow runs the caller's validation script before publishing. This check
must verify the meaning of the changes, such as valid catalog IDs or working
document references. A successful CLI exit does not establish correctness.

A caller uses the same PR fields as the Python example, with these changes:

```yaml
secrets:
  CHERRY_PICK_APP_PRIVATE_KEY: ${{ secrets.CHERRY_PICK_APP_PRIVATE_KEY }}
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
with:
  task-runner: claude-code
  prompt-file: .github/prompts/<task>.md
  validation-script: .github/scripts/<validator>.py
  files: <approved-file-or-directory>
  agent-model: claude-opus-5-5
  agent-max-turns: 60
  agent-timeout-seconds: 1200
```

`fallback-script` and `fallback-args` select a deterministic fallback when the
chosen adapter fails or lacks its API key. The same output validation runs after
the fallback. Without a fallback, an adapter failure fails the workflow.
Repair tasks receive the earlier validation logs as untrusted context.

## Use the runner in another workflow

`run-coding-agent` is a composite action. The CVE workflow uses it within its
existing triage and publishing flow. CVE retains its report validation and transfers
approved manifest edits into a clean checkout before regenerating lockfiles.

```yaml
- uses: ./.github/actions/run-coding-agent
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    RESULT_FILE: ${{ runner.temp }}/task/result.json
  with:
    prompt-file: .github/prompts/<task>.md
    working-directory: <task-checkout>
    prompt-vars: RESULT_FILE
    additional-directories: ${{ runner.temp }}/task
    model: claude-opus-5-5
```

Without `allowed-files`, the action runs in the supplied checkout and does not
transfer or validate edits. The caller must enforce its own output boundary, as CVE does.
Use `allowed-files` for the isolated transfer behavior described above.

The action requires Python 3 and npm's `npx`, available on the hosted Ubuntu runner.
It pins the Claude Code version in `.github/scripts/run_coding_agent.py`.
It disables repository hooks, settings, and MCP configuration. Agent tools are
limited to Read, Glob, Grep, Edit, and Write. Shell and code execution tools are disabled.

Use `prompt-vars` to name environment variables that the prompt can reference.
Only those names are substituted. Inputs and repository content remain untrusted
data; prompts must not delegate their edit rules to repository instructions.

## Add another harness

Add an adapter in `run_coding_agent.py`, with explicit authentication and launch
arguments. Test its permission policy, failures, and timeout handling. Expose its
name through the action and the reusable workflow's configuration check.
Keep prompts, domain validation, and PR publishing outside the adapter.

## Checks

```bash
python3 -m unittest discover -s .github/scripts -p test_run_coding_agent.py
pre-commit run --files .github/scripts/run_coding_agent.py \
  .github/scripts/test_run_coding_agent.py \
  .github/actions/run-coding-agent/action.yml \
  .github/workflows/reusable-agent-task-pr.yml \
  .github/workflows/cve-alerts.yml \
  .github/workflows/pr-quality-checks.yml
```
