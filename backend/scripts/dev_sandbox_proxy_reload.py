"""Run the sandbox proxy with watchfiles hot-reload, preserving VSCode breakpoints.

LOAD-BEARING: referenced by the `sandboxProxy.command` override in
deployment/helm/charts/onyx/values-tilt.yaml. Deleting or renaming this file
breaks hot-reload of sandbox-proxy under the Tilt local-dev workflow. See
docs/dev/craft-tilt-dev.md.

Mirrors dev_celery_reload.py: the reloader runs inside the debugged process
and re-launches the target via fork; debugpy follows the fork when launch.json
sets `subProcess: true`. The watchfiles parent forwards SIGTERM cleanly to the
child, which already has signal-driven graceful shutdown in
onyx.sandbox_proxy.server.
"""

import os
import sys

from watchfiles import run_process


def _run() -> None:
    from onyx.sandbox_proxy.server import main  # ty: ignore[unresolved-import]

    sys.exit(main())


if __name__ == "__main__":
    watch_paths = [p for p in ("./onyx", "./ee") if os.path.isdir(p)]
    run_process(*watch_paths, target=_run)
