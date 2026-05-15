"""Run a celery worker with watchfiles hot-reload, preserving VSCode breakpoints.

LOAD-BEARING: referenced by every "Celery <name>" configuration in
.vscode/launch.json (both local and k8s variants). Deleting or renaming this
file will break the vscode debugger for celery. See also CONTRIBUTING.md
("VSCode Debugger") and docs/dev/local-kubernetes.md.

The reloader runs inside the debugged process and re-launches via fork;
debugpy follows the fork when launch.json sets `subProcess: true`. The
`watchmedo auto-restart -- celery worker` pattern spawns celery as a bare
subprocess that debugpy can't attach to.

Args after the script name are forwarded verbatim to celery's CLI.

Example launch.json entry:
    program: ${workspaceFolder}/backend/scripts/dev_celery_reload.py
    args: ["-A", "onyx.background.celery.versioned_apps.primary", "worker",
           "--pool=threads", "-Q", "celery", ...]
    subProcess: true
"""

import sys

from watchfiles import run_process


def _run(argv: list[str]) -> None:
    from celery.__main__ import main  # ty: ignore[unresolved-import]

    sys.argv[:] = argv
    main()


if __name__ == "__main__":
    celery_argv = ["celery", *sys.argv[1:]]
    import os

    watch_paths = [p for p in ("./onyx", "./ee") if os.path.isdir(p)]
    run_process(*watch_paths, target=_run, args=(celery_argv,))
