"""Process entry point for the Onyx model server (`python -m model_server`).

The `DISABLE_MODEL_SERVER` short-circuit used to live in the container command as a
shell `if`. Hardened base images ship without `sh`/`bash`, so the gate runs here in
Python instead. It is intentionally kept in front of `model_server.main`'s imports so a
disabled container exits without pulling in torch / the ML stack — matching the old
behavior where the shell exited before Python ever started.
"""

import sys

from onyx.utils.logger import setup_logger
from shared_configs.configs import DISABLE_MODEL_SERVER

logger = setup_logger()


def main() -> None:
    if DISABLE_MODEL_SERVER:
        # The deployment points inference/indexing at an external model server, so this
        # container has nothing to run. Exit cleanly instead of starting uvicorn.
        logger.notice("DISABLE_MODEL_SERVER is set; skipping model server startup.")
        sys.exit(0)

    # Imported lazily so the disabled path above stays free of the heavy ML imports.
    from model_server.main import run_server

    run_server()


if __name__ == "__main__":
    main()
