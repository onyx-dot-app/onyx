# Codex hook checks

Run the read-only diagnostic from the checkout root:

```bash
python3 .agents/hooks/hook_health.py .
```

The diagnostic prints one JSON record. `static_status` checks the hook files,
Git root, pre-commit config, ignore rules, and pre-commit executable. A value
of `ok` means those files and commands are available. It does not prove that
Codex ran the hooks.

`runtime_status` reports `disabled` when local Codex state explicitly disables
either project event. It reports `unverified` in every other case. A saved trust
hash does not prove that it matches the current definition or that an event ran.
The overall `status` is `degraded` until runtime behavior is observed. A broken
hook command or missing Git checkout reports `failed`.

In a new Codex session rooted at this checkout, use `/hooks` to review the
project `UserPromptSubmit` and `Stop` handlers. Confirm that both are enabled
and trusted. Then observe one prompt and Stop cycle. The prompt event records a
snapshot under the checkout's Git directory. The Stop event checks files
changed after that snapshot. Review hook output for a missing prerequisite
warning or a pre-commit failure.

The hook returns a warning without stopping the turn when the project
pre-commit config, prompt snapshot, or pre-commit executable is missing. It
still uses exit code 2 when pre-commit or the feature-map check finds work to
fix. A repeated Stop event is allowed through to avoid a continuation loop.

Run focused tests:

```bash
cd .agents/hooks
python3 -m unittest -v test_hook_health.py test_pre_commit_on_stop.py
```

Do not edit Codex trust hashes directly. Do not bypass hook trust to make a
health check pass.
