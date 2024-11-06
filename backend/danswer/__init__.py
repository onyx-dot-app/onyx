import os

__version__ = os.environ.get("DANSWER_VERSION", "") or "Development"
