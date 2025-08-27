from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.models import UserFolder
from onyx.db.projects import upload_files_to_user_files_with_indexing
from onyx.server.projects.models import UserFileSnapshot
from onyx.server.projects.models import UserProjectSnapshot
from onyx.utils.logger import setup_logger

logger = setup_logger()


router = APIRouter(prefix="/user/projects")


@router.get("/")
def get_projects(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserProjectSnapshot]:
    projects = db_session.query(UserFolder).filter(UserFolder.user_id == user.id).all()
    return [UserProjectSnapshot.from_model(project) for project in projects]


@router.post("/create")
def create_project(
    name: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UserProjectSnapshot:
    project = UserFolder(name=name, user_id=user.id)
    db_session.add(project)
    db_session.commit()
    return UserProjectSnapshot.from_model(project)


@router.post("/file/upload")
def upload_user_files(
    files: list[UploadFile] = File(...),
    project_id: int | None = Form(None),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserFileSnapshot]:
    try:
        # Use our consolidated function that handles indexing properly
        user_files = upload_files_to_user_files_with_indexing(
            files=files, project_id=project_id, user=user, db_session=db_session
        )

        return [UserFileSnapshot.from_model(user_file) for user_file in user_files]

    except Exception as e:
        logger.error(f"Error uploading files: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to upload files: {str(e)}")


@router.get("/files/{project_id}")
def get_files_in_project(
    project_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserFileSnapshot]:
    user_files = (
        db_session.query(UserFile)
        .filter(UserFile.projects.any(id=project_id), UserFile.user_id == user.id)
        .all()
    )
    return [UserFileSnapshot.from_model(user_file) for user_file in user_files]
