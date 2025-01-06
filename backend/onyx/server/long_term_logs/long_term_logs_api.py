import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from onyx.auth.users import current_admin_user
from onyx.db.models import User
from onyx.utils.long_term_log import LongTermLogger

router = APIRouter(prefix="/admin/long-term-logs")


@router.get("/{category}")
def get_long_term_logs(
    category: str,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    _: User | None = Depends(current_admin_user),
) -> list[dict | list | str]:
    """Fetch logs for a specific category within an optional time range.
    Only accessible by admin users."""
    try:
        logger = LongTermLogger()
        return logger.fetch_category(  # type: ignore
            category=category,
            start_time=start_time,
            end_time=end_time,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch logs for category '{category}': {str(e)}",
        )


@router.get("/{category}/download")
def download_long_term_logs_zip(
    category: str,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    _: User | None = Depends(current_admin_user),
) -> FileResponse:
    """Download logs for a specific category as a ZIP file.
    Only accessible by admin users."""
    try:
        logger = LongTermLogger()
        logs = logger.fetch_category(
            category=category,
            start_time=start_time,
            end_time=end_time,
        )

        # Create temporary files without using context manager
        temp_dir = tempfile.mkdtemp()
        temp_dir_path = Path(temp_dir)

        # Create JSON file
        json_path = temp_dir_path / f"{category}-logs.json"
        with open(json_path, "w") as f:
            json.dump(logs, f, indent=2, default=str)

        # Create ZIP file
        zip_path = temp_dir_path / f"{category}-logs.zip"
        with zipfile.ZipFile(zip_path, "w") as zip_file:
            zip_file.write(json_path, json_path.name)

        # Let FastAPI handle cleanup by setting background tasks
        return FileResponse(
            path=zip_path,
            filename=f"{category}-logs.zip",
            media_type="application/zip",
            background=BackgroundTask(
                lambda: shutil.rmtree(temp_dir, ignore_errors=True)
            ),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create ZIP file for category '{category}': {str(e)}",
        )


@router.get("")
def get_available_categories(
    _: User | None = Depends(current_admin_user),
) -> list[str]:
    """Get a list of all available log categories.
    Only accessible by admin users."""
    try:
        logger = LongTermLogger()
        # Get all subdirectories in the log directory
        categories = [d.name for d in logger.log_file_path.iterdir() if d.is_dir()]
        return categories
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch log categories: {str(e)}"
        )
