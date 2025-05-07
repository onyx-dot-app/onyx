from typing import Any

from slack_sdk import WebClient
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import NoResultFound

from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.persona import fetch_persona_by_id
from danswer.db.users import add_slack_persona_for_user
from danswer.db.users import add_user_slack_persona
from danswer.db.users import fetch_user_slack_persona
from danswer.utils.logger import setup_logger

logger = setup_logger()


def handle_modal_submission(client: WebClient, body: dict[str, Any]) -> None:
    """Handle the submission of the persona selection modal"""
    try:
        # Get the selected persona ID from the modal submission
        selected_persona_id = body["view"]["state"]["values"]["persona_selection"][
            "select_persona"
        ]["selected_option"]["value"]

        user_id = body["user"]["id"]

        channel_id = body["view"]["private_metadata"]

        with Session(get_sqlalchemy_engine()) as db_session:
            try:
                persona = fetch_persona_by_id(
                    db_session=db_session, persona_id=selected_persona_id
                )

                if persona is None:
                    return {
                        "response_action": "errors",
                        "errors": {"persona_selection": "Persona not found."},
                    }

                user_slack_persona = fetch_user_slack_persona(
                    db_session=db_session, sender_id=user_id
                )
                if user_slack_persona:
                    add_slack_persona_for_user(
                        db_session=db_session,
                        persona=persona,
                        user_slack_persona=user_slack_persona,
                    )
                    response_text = f"Persona '{persona.name}' has been set!"
                    client.chat_postMessage(channel=channel_id, text=response_text)
                    return {"response_action": "clear"}

                else:
                    add_user_slack_persona(
                        db_session=db_session, sender_id=user_id, persona=persona
                    )
                    client.chat_postMessage(
                        channel=channel_id,
                        text=f"'{persona.name}' has been successfully set as the current persona.",
                    )
                    return {"response_action": "clear"}

            except NoResultFound:
                return {
                    "response_action": "errors",
                    "errors": {"persona_selection": "Error in fetching persona"},
                }

    except Exception as e:
        logger.error(f"Error handling modal submission: {e}")
        return {
            "response_action": "errors",
            "errors": {
                "persona_selection": "Sorry, there was an error updating your persona. Please try again."
            },
        }
