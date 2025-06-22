from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.input_prompt import disable_input_prompt_for_user
from onyx.db.input_prompt import fetch_input_prompt_by_id
from onyx.db.input_prompt import fetch_input_prompts_by_user
from onyx.db.input_prompt import insert_input_prompt
from onyx.db.input_prompt import remove_input_prompt
from onyx.db.input_prompt import remove_public_input_prompt
from onyx.db.input_prompt import update_input_prompt
from onyx.db.models import InputPrompt__User
from onyx.db.models import User
from onyx.server.features.input_prompt.models import CreateInputPromptRequest
from onyx.server.features.input_prompt.models import InputPromptSnapshot
from onyx.server.features.input_prompt.models import UpdateInputPromptRequest
from onyx.utils.logger import setup_logger

logger = setup_logger()

basic_router = APIRouter(prefix="/input_prompt")
admin_router = APIRouter(prefix="/admin/input_prompt")


@basic_router.get("")
def list_input_prompts(
    user: User | None = Depends(current_user),
    include_public: bool = True,
    db_session: Session = Depends(get_session),
) -> list[InputPromptSnapshot]:
    user_prompts = fetch_input_prompts_by_user(
        user_id=user.id if user is not None else None,
        db_session=db_session,
        include_public=include_public,
    )
    return [InputPromptSnapshot.from_model(prompt) for prompt in user_prompts]


@basic_router.get("/{input_prompt_id}")
def get_input_prompt(
    input_prompt_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> InputPromptSnapshot:
    input_prompt = fetch_input_prompt_by_id(
        id=input_prompt_id,
        user_id=user.id if user is not None else None,
        db_session=db_session,
    )

    return InputPromptSnapshot.from_model(input_prompt=input_prompt)


@basic_router.post("")
def create_input_prompt(
    create_input_prompt_request: CreateInputPromptRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> InputPromptSnapshot:
    input_prompt = insert_input_prompt(
        prompt=create_input_prompt_request.prompt,
        content=create_input_prompt_request.content,
        is_public=False,
        user=user,
        db_session=db_session,
    )

    if user is not None:
        input_prompt_user = InputPrompt__User(
            input_prompt_id=input_prompt.id, user_id=user.id
        )
        db_session.add(input_prompt_user)
        db_session.commit()

    return InputPromptSnapshot.from_model(input_prompt)


@basic_router.patch("/{input_prompt_id}")
def patch_input_prompt(
    input_prompt_id: int,
    update_input_prompt_request: UpdateInputPromptRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> InputPromptSnapshot:
    try:
        updated_input_prompt = update_input_prompt(
            user=user,
            input_prompt_id=input_prompt_id,
            prompt=update_input_prompt_request.prompt,
            content=update_input_prompt_request.content,
            active=update_input_prompt_request.active,
            db_session=db_session,
        )
    except ValueError as e:
        error_msg = "Error occurred while updated input prompt"
        logger.warn(f"{error_msg}. Stack trace: {e}")
        raise HTTPException(status_code=404, detail=error_msg)

    return InputPromptSnapshot.from_model(updated_input_prompt)


@basic_router.delete("/{input_prompt_id}")
def delete_input_prompt(
    input_prompt_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
    delete_public: bool = False,
) -> None:
    try:
        remove_input_prompt(
            user, input_prompt_id, db_session, delete_public=delete_public
        )

    except ValueError as e:
        error_msg = "Error occurred while deleting input prompt"
        logger.warn(f"{error_msg}. Stack trace: {e}")
        raise HTTPException(status_code=404, detail=error_msg)


@admin_router.delete("/{input_prompt_id}")
def delete_public_input_prompt(
    input_prompt_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    try:
        remove_public_input_prompt(input_prompt_id, db_session)

    except ValueError as e:
        error_msg = "Error occurred while deleting input prompt"
        logger.warn(f"{error_msg}. Stack trace: {e}")
        raise HTTPException(status_code=404, detail=error_msg)


@basic_router.post("/{input_prompt_id}/hide")
def hide_input_prompt_for_user(
    input_prompt_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    """
    Endpoint that marks a seed (or any) prompt as disabled for the current user,
    so it won't show up in their subsequent queries.
    """
    if user is None:
        # if auth is disabled, just delete the prompt
        delete_input_prompt(input_prompt_id, user, db_session, delete_public=True)

    else:
        disable_input_prompt_for_user(input_prompt_id, user.id, db_session)

    return None
