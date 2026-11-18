import os

__version__ = os.environ.get("ONYX_VERSION", "") or "Development"
# Throwaway stack CI test 1. Do not merge.
