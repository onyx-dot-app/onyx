import json
from slack_sdk.socket_mode.request import SocketModeRequest

from onyx.chat.models import ThreadMessage
from onyx.configs.app_configs import DEV_MODE
from onyx.configs.app_configs import POD_NAME
from onyx.configs.app_configs import POD_NAMESPACE
from onyx.configs.constants import MessageType
from onyx.configs.onyxbot_configs import DANSWER_BOT_REPHRASE_MESSAGE
from onyx.configs.onyxbot_configs import DANSWER_BOT_RESPOND_EVERY_CHANNEL
from onyx.configs.onyxbot_configs import NOTIFY_SLACKBOT_NO_ANSWER
from onyx.connectors.slack.utils import expert_info_from_slack_id
from onyx.db.engine import get_session_with_current_tenant

from onyx.onyxbot.slack.handlers.handle_message import handle_message
from onyx.onyxbot.slack.handlers.handle_message import (
    remove_scheduled_feedback_reminder,
)
from onyx.onyxbot.slack.handlers.handle_message import schedule_feedback_reminder
from onyx.onyxbot.slack.models import SlackMessageInfo
from onyx.onyxbot.slack.utils import read_slack_thread
from onyx.onyxbot.slack.utils import respond_in_thread_or_channel
from onyx.onyxbot.slack.utils import TenantSocketModeClient
from onyx.db.models import SlackShortcutConfig
from onyx.utils.logger import setup_logger
from onyx.onyxbot.slack.utils import (
    fetch_slack_user_ids_from_emails,
    fetch_user_ids_from_groups
)

logger = setup_logger()

def handle_shortcut_modal_submission(
    req: SocketModeRequest,
    client: TenantSocketModeClient,
) -> None:
    """
    Handle the submission of the shortcut prompt modal.
    This processes the user's input and then calls the appropriate handler.
    """
    try:
        # Get the private metadata to retrieve shortcut config and message context
        private_metadata = json.loads(req.payload["view"]["private_metadata"])
        shortcut_config_id = private_metadata.get("shortcut_config_id")
        message_context = private_metadata.get("message_context", {})
        
        # Get the user's input from the modal
        user_prompt = req.payload["view"]["state"]["values"]["prompt_input"]["prompt_text"]["value"]
        
        # Extract message context
        channel_id = message_context.get("channel_id")
        message_ts = message_context.get("message_ts")
        thread_ts = message_context.get("thread_ts")
        user_id = message_context.get("user_id")
        original_text = message_context.get("original_text")
        
        with get_session_with_current_tenant() as db_session:
            # Get the shortcut configuration
            slack_shortcut_config = db_session.query(SlackShortcutConfig).filter_by(id=shortcut_config_id).first()
            
            if not slack_shortcut_config:
                logger.error(f"Shortcut configuration with ID {shortcut_config_id} not found")
                respond_in_thread_or_channel(
                    client=client.web_client,
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text="Sorry, the shortcut configuration could not be found.",
                    is_ephemeral=True,
                    user_id=user_id,
                )
                return
            
            # Build the necessary message info with the user's prompt
            thread_messages = read_slack_thread(
                channel=channel_id, 
                thread=thread_ts, 
                client=client.web_client
            )
            
            # Replace the last message with user's prompt if it was a thread
            # Otherwise, create a new message with the user's prompt
            if thread_messages:
                last_message = thread_messages[-1]
                new_thread_messages = thread_messages[:-1] + [
                    ThreadMessage(
                        message=user_prompt,
                        sender=last_message.sender,
                        role=last_message.role 
                    )
                ]
            else:
                # No thread exists, create a single message
                expert_info = expert_info_from_slack_id(
                    user_id, client.web_client, user_cache={}
                )
                sender_display_name = None
                if expert_info:
                    sender_display_name = expert_info.display_name
                    if sender_display_name is None:
                        sender_display_name = (
                            f"{expert_info.first_name} {expert_info.last_name}"
                            if expert_info.last_name
                            else expert_info.first_name
                        )
                    if sender_display_name is None:
                        sender_display_name = expert_info.email
                
                new_thread_messages = [
                    ThreadMessage(
                        message=user_prompt, 
                        sender=sender_display_name, 
                        role=MessageType.USER
                    )
                ]
            
            # Create SlackMessageInfo with the new prompt
            message_info = SlackMessageInfo(
                thread_messages=new_thread_messages,
                channel_to_respond=channel_id,
                msg_to_respond=message_ts,
                thread_to_respond=thread_ts,
                sender_id=user_id,
                email=None,  # Will be filled in by handle_message
                bypass_filters=True,  # Shortcuts bypass filters
                is_bot_msg=False,
                is_bot_dm=False,
                is_shortcut=True,
            )
            
            # Determine if the response should be ephemeral
            is_ephemeral = slack_shortcut_config.shortcut_config.get("is_ephemeral", False)
            
            # Check respond_member_group_list restriction
            respond_member_group_list = slack_shortcut_config.shortcut_config.get("respond_member_group_list")
            send_to = None
            if respond_member_group_list:
                send_to, missing_ids = fetch_slack_user_ids_from_emails(
                    respond_member_group_list, client.web_client
                )
                
                user_ids, missing_users = fetch_user_ids_from_groups(missing_ids, client.web_client)
                send_to = list(set(send_to + user_ids)) if send_to else user_ids
                
                if missing_users:
                    logger.warning(f"Failed to find these users/groups: {missing_users}")
                    
                # Check if the current user is in the allowed list
                if user_id and send_to and user_id not in send_to:
                    logger.info(f"User {user_id} is not in the allowed list for this shortcut.")
                    respond_in_thread_or_channel(
                        client=client.web_client,
                        channel=channel_id,
                        thread_ts=None,
                        text="You don't have permission to use this shortcut.",
                        is_ephemeral=True,
                        user_id=user_id,
                    )
                    return
            
            # Check for follow-up configuration
            follow_up = bool(slack_shortcut_config.shortcut_config.get("follow_up_tags") is not None)
            
            # Schedule feedback reminder if needed
            feedback_reminder_id = None
            if slack_shortcut_config.shortcut_config.get("show_continue_in_web_ui", False):
                feedback_reminder_id = schedule_feedback_reminder(
                    details=message_info, 
                    client=client.web_client, 
                    include_followup=follow_up
                )
            
            # Now process the message with the user's prompt
            failed = handle_message(
                message_info=message_info,
                slack_channel_config=None,
                slack_shortcut_config=slack_shortcut_config,
                client=client.web_client,
                feedback_reminder_id=feedback_reminder_id,
            )
            
            if failed:
                if feedback_reminder_id:
                    remove_scheduled_feedback_reminder(
                        client=client.web_client,
                        channel=user_id,
                        msg_id=feedback_reminder_id,
                    )
                
                respond_in_thread_or_channel(
                    client=client.web_client,
                    channel=channel_id,
                    thread_ts=thread_ts,
                    text="Sorry, I wasn't able to find anything relevant :cold_sweat:",
                    send_as_ephemeral=is_ephemeral,
                    user_id=user_id if is_ephemeral else None,
                )
                
    except Exception as e:
        logger.exception(f"Error handling shortcut modal submission: {e}")
        # Try to notify the user of the error
        try:
            user_id = req.payload.get("user", {}).get("id")
            if user_id:
                client.web_client.chat_postEphemeral(
                    channel=req.payload.get("view", {}).get("private_metadata", {}).get("message_context", {}).get("channel_id", ""),
                    user=user_id,
                    text="Sorry, there was an error processing your request."
                )
        except:
            pass