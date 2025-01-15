import os

__version__ = os.environ.get("ONYX_VERSION", "") or "Development"
