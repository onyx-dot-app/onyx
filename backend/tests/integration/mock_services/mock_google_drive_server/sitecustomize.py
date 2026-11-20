"""Points a running Onyx at the mock Drive server, with no change to Onyx.

Python imports ``sitecustomize`` at startup when its directory is on the
path. To use it, start the API server and every Celery worker with:

    PYTHONPATH=<this directory> MOCK_GDRIVE_URL=http://localhost:9650/

Without ``MOCK_GDRIVE_URL`` this file does nothing. See README.md.
"""

import os

_MOCK_URL = os.environ.get("MOCK_GDRIVE_URL", "").strip()

if _MOCK_URL:
    # This directory is on the path when this file runs.
    from mock_gdrive.patch_onyx import (  # ty: ignore[unresolved-import]
        install_for_process,
    )

    install_for_process(_MOCK_URL)
