import yaml
from sqlalchemy.orm import Session

from onyx.configs.chat_configs import INPUT_PROMPT_YAML
from onyx.configs.chat_configs import USER_FOLDERS_YAML
from onyx.db.input_prompt import insert_input_prompt_if_not_exists
from onyx.db.user_documents import upsert_user_folder
from onyx.utils.logger import setup_logger


logger = setup_logger()


def load_user_folders_from_yaml(
    db_session: Session,
    user_folders_yaml: str = USER_FOLDERS_YAML,
) -> None:
    with open(user_folders_yaml, "r") as file:
        data = yaml.safe_load(file)

    all_user_folders = data.get("user_folders", [])
    for user_folder in all_user_folders:
        upsert_user_folder(
            db_session=db_session,
            id=user_folder.get("id"),
            name=user_folder.get("name"),
            description=user_folder.get("description"),
            created_at=user_folder.get("created_at"),
            user=user_folder.get("user"),
            files=user_folder.get("files"),
            assistants=user_folder.get("assistants"),
        )
    db_session.flush()


def load_input_prompts_from_yaml(
    db_session: Session, input_prompts_yaml: str = INPUT_PROMPT_YAML
) -> None:
    with open(input_prompts_yaml, "r") as file:
        data = yaml.safe_load(file)

    all_input_prompts = data.get("input_prompts", [])
    for input_prompt in all_input_prompts:
        # If these prompts are deleted (which is a hard delete in the DB), on server startup
        # they will be recreated, but the user can always just deactivate them, just a light inconvenience

        insert_input_prompt_if_not_exists(
            user=None,
            input_prompt_id=input_prompt.get("id"),
            prompt=input_prompt["prompt"],
            content=input_prompt["content"],
            is_public=input_prompt["is_public"],
            active=input_prompt.get("active", True),
            db_session=db_session,
            commit=True,
        )


def load_chat_yamls(
    db_session: Session,
    input_prompts_yaml: str = INPUT_PROMPT_YAML,
) -> None:
    """Load all chat-related YAML configurations and builtin personas."""
    load_input_prompts_from_yaml(db_session, input_prompts_yaml)
    load_user_folders_from_yaml(db_session)
