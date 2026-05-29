"""Optional in-process debugpy listener for the local-cluster dev path.

When `ENABLE_DEBUGPY=true`, opens a debugpy listener on `DEBUGPY_PORT`
(default 5678) and returns. Inert otherwise (no import of debugpy on prod
images that don't ship it).

Called from:
- `backend/onyx/main.py` at module load — api server uvicorn worker
- celery's `worker_init` signal handler in `apps/app_base.py` — each
  celery worker

The listener runs INSIDE the application process, so:
- VSCode attaches directly via Tilt's port-forward, no outer
  `python -m debugpy --listen ... -m uvicorn` wrap needed.
- `uvicorn --reload` reuses the parent's import cache and re-execs only
  the worker child; the new worker calls `maybe_listen()` again on
  startup. VSCode's attach config has `restart: true` so it reattaches.
- Celery workers get the same treatment via `worker_init`.

This is the local-cluster dev path. Production images don't set
`ENABLE_DEBUGPY` and don't pip-install debugpy, so this module is a
no-op in prod.
"""

import os


def maybe_listen() -> None:
    if os.environ.get("ENABLE_DEBUGPY", "").lower() != "true":
        return
    try:
        import debugpy
    except ImportError:
        # Prod image doesn't ship debugpy. Silent no-op.
        return
    port = int(os.environ.get("DEBUGPY_PORT", "5678"))
    try:
        debugpy.listen(("0.0.0.0", port))  # noqa: S104 - dev-only, in-cluster pod IP
        print(f"[debugpy] listening on 0.0.0.0:{port}", flush=True)
    except RuntimeError as e:
        # `debugpy.listen` raises if called twice on the same port in the
        # same process (rare, but possible across import paths). Treat as
        # benign — we already have a listener.
        if "already" in str(e).lower():
            return
        print(f"[debugpy] failed to listen on :{port}: {e}", flush=True)
