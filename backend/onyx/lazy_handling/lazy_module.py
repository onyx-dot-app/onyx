import importlib
import threading
from typing import Any


class LazyModule:
    def __init__(self, module_name: str):
        self.module_name = module_name
        self._module: Any = None
        self._lock = threading.Lock()
        self._import_failed = False

    def __getattr__(self, name: str) -> Any:
        if self._import_failed:
            raise ImportError(f"Previous import of '{self.module_name}' failed")

        if self._module is None:
            with self._lock:
                if self._module is None and not self._import_failed:
                    try:
                        self._module = importlib.import_module(self.module_name)
                    except (ImportError, ValueError) as e:
                        self._import_failed = True
                        raise ImportError(
                            f"Failed to import '{self.module_name}': {e}. "
                            f"Ensure the package is installed."
                        ) from e

        try:
            return getattr(self._module, name)
        except AttributeError as e:
            raise AttributeError(
                f"Module '{self.module_name}' has no attribute '{name}'"
            ) from e
