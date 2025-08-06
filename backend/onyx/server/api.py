from fastapi import APIRouter, Depends, HTTPException
from onyx.auth.users import current_active_user
from onyx.db.models import IndexAttempt
from onyx.db import get_db
from sqlalchemy.orm import Session

# Define the router with authentication dependency
router = APIRouter(dependencies=[Depends(current_active_user)])

@router.get("/indexing-status/{attempt_id}")
async def get_indexing_status(attempt_id: int, db: Session = Depends(get_db)):
    """
    Retrieve the indexing status for a given attempt ID.
    
    Args:
        attempt_id (int): The ID of the indexing attempt.
        db (Session): The database session, injected via dependency.
    
    Returns:
        dict: A dictionary containing progress details of the indexing attempt.
    
    Raises:
        HTTPException: If the indexing attempt is not found (404).
    """
    attempt = db.query(IndexAttempt).filter(IndexAttempt.id == attempt_id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="Index attempt not found")
    return {
        "file_type": attempt.file_type or "unknown",
        "completed_pages": attempt.processed_pages,
        "total_pages": attempt.total_pages,
        "completed_slides": attempt.processed_slides,
        "total_slides": attempt.total_slides,
        "completed_sheets": attempt.processed_sheets,
        "total_sheets": attempt.total_sheets,
        "completed_sections": attempt.processed_sections,
        "total_sections": attempt.total_sections,
        "completed_batches": attempt.completed_batches,
        "total_batches": attempt.total_batches,
        "is_complete": attempt.is_complete
    }
