import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro

logger = setup_logger()

_LOG_FILE_NAME_TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S-%f"


class LongTermLogger:
    """NOTE: should support a LOT of data AND should be extremely fast,
    ideally done in a background thread."""

    def __init__(
        self,
        metadata: dict[str, str] | None = None,
        log_file_path: str = "/tmp/long_term_log",
        max_files_per_category: int = 1000,
    ):
        self.metadata = metadata
        self.log_file_path = Path(log_file_path)
        self.max_files_per_category = max_files_per_category
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
        except Exception:
            # logger.error(f"Error creating directory for long-term logs: {e}")
            pass

    def _cleanup_old_files(self, category_path: Path) -> None:
        try:
            files = sorted(
                [f for f in category_path.glob("*.json")],
                key=lambda x: x.stat().st_mtime,  # Sort by modification time
                reverse=True,
            )

            # Delete oldest files that exceed the limit
            for file in files[self.max_files_per_category :]:
                if not file.is_file():
                    logger.debug(f"File already deleted: {file}")
                    continue
                try:
                    file.unlink()
                except Exception:
                    pass
                    # logger.error(f"Error deleting old log file {file
                    # }: {e}")
        except Exception:
            pass
            # logger.error(f"Error during log rotation cleanup: {e}")

    def _record(self, message: Any, category: str) -> None:
        category_path = self.log_file_path / category
        try:
            # Create directory if it doesn't exist
            os.makedirs(category_path, exist_ok=True)

            # Perform cleanup before writing new file
            self._cleanup_old_files(category_path)

            final_record = {
                "metadata": self.metadata,
                "record": message,
            }

            file_path = (
                category_path
                / f"{datetime.now().strftime(_LOG_FILE_NAME_TIMESTAMP_FORMAT)}.json"
            )
            with open(file_path, "w+") as f:
                # default allows us to "ignore" unserializable objects
                json.dump(final_record, f, default=lambda x: str(x))
        except Exception:
            # logger.error(f"Error recording log: {e}")
            pass

    def record(self, message: JSON_ro, category: str = "default") -> None:
        try:
            # Run in separate thread to have minimal overhead in main flows
            thread = threading.Thread(
                target=self._record, args=(message, category), daemon=True
            )
            thread.start()
        except Exception:
            # Should never interfere with normal functions of Onyx
            pass

    def fetch_category(
        self,
        category: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[JSON_ro]:
        category_path = self.log_file_path / category
        files = list(category_path.glob("*.json"))

        results: list[JSON_ro] = []
        for file in files:
            # Parse timestamp from filename (YYYY-MM-DD_HH-MM-SS.json)
            try:
                file_time = datetime.strptime(
                    file.stem, _LOG_FILE_NAME_TIMESTAMP_FORMAT
                )

                # Skip if outside time range
                if start_time and file_time < start_time:
                    continue
                if end_time and file_time > end_time:
                    continue

                results.append(json.loads(file.read_text()))
            except ValueError:
                # Skip files that don't match expected format
                continue

        return results
