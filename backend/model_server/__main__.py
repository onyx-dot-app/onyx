"""Process entry point for the model server (`python -m model_server`).

The `DISABLE_MODEL_SERVER` gate runs here, ahead of `model_server.main`'s heavy ML
imports, so a disabled container exits without loading torch / the model stack.
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
