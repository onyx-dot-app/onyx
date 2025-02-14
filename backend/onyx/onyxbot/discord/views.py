import discord
from sqlalchemy import select

from onyx.configs.constants import MessageType
from onyx.configs.constants import SearchFeedbackType
from onyx.db.engine import get_session_with_tenant
from onyx.db.feedback import create_chat_message_feedback
from onyx.db.feedback import create_doc_retrieval_feedback
from onyx.db.models import ChatMessage
from onyx.utils.logger import setup_logger

logger = setup_logger()


class BaseFeedbackView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.feedback_message = None

    async def process_feedback(
        self,
        interaction: discord.Interaction,
        is_positive: bool,
        positive_button_id: str,
        negative_button_id: str,
    ):
        try:
            for child in self.children:
                if child.custom_id == positive_button_id:
                    child.style = (
                        discord.ButtonStyle.green
                        if is_positive
                        else discord.ButtonStyle.grey
                    )
                    child.disabled = is_positive
                elif child.custom_id == negative_button_id:
                    child.style = (
                        discord.ButtonStyle.red
                        if not is_positive
                        else discord.ButtonStyle.grey
                    )
                    child.disabled = not is_positive

            await interaction.message.edit(view=self)

            response_message = await self.get_feedback_message(is_positive)

            if self.feedback_message:
                try:
                    await self.feedback_message.edit(content=response_message)
                    await interaction.response.defer()
                except Exception:
                    self.feedback_message = await interaction.response.send_message(
                        response_message, ephemeral=True
                    )
            else:
                self.feedback_message = await interaction.response.send_message(
                    response_message, ephemeral=True
                )

            await self.handle_feedback(interaction, is_positive)

        except Exception:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Sorry, there was an error processing your feedback.",
                    ephemeral=True,
                )

    async def get_feedback_message(self, is_positive: bool) -> str:
        """Override this method to provide specific feedback messages"""
        raise NotImplementedError

    async def handle_feedback(
        self, interaction: discord.Interaction, is_positive: bool
    ):
        """Override this method to handle feedback storage/processing"""
        raise NotImplementedError


class FeedbackView(BaseFeedbackView):
    def __init__(
        self, message_id: int, tenant_id: str, users_to_tag: list[str] | None = None
    ):
        super().__init__()
        self.message_id = message_id
        self.tenant_id = tenant_id
        self.users_to_tag = users_to_tag

    async def process_feedback(
        self,
        interaction: discord.Interaction,
        is_positive: bool,
        pos_id: str,
        neg_id: str,
    ):
        # Update button states
        for child in self.children:
            if child.custom_id == (pos_id if is_positive else neg_id):
                child.disabled = True
                child.style = (
                    discord.ButtonStyle.green
                    if is_positive
                    else discord.ButtonStyle.red
                )
            elif child.custom_id == (neg_id if is_positive else pos_id):
                child.disabled = False
                child.style = discord.ButtonStyle.grey

        # Create new view with updated buttons
        new_view = discord.ui.View()

        # Add feedback buttons first
        for item in self.children:
            new_view.add_item(item)

        # Add "Still need help" button with the preserved users_to_tag
        help_view = StillNeedHelpView(users_to_tag=self.users_to_tag)
        for component in interaction.message.components[0].children:
            if component.custom_id not in ["helpful", "not_helpful"]:
                for help_item in help_view.children:
                    help_item.disabled = component.disabled
                    help_item.style = component.style
                    new_view.add_item(help_item)

        await interaction.message.edit(view=new_view)

        # Send feedback confirmation message
        feedback_message = (
            "Thanks for the feedback!"
            if is_positive
            else "Thanks for letting us know this wasn't helpful. We'll work on improving!"
        )
        await interaction.response.send_message(feedback_message, ephemeral=True)

        await self.handle_feedback(interaction, is_positive)

    async def handle_feedback(
        self, interaction: discord.Interaction, is_positive: bool
    ):
        if not interaction.message or not interaction.message.reference:
            await interaction.response.defer()
            return

        try:
            with get_session_with_tenant(self.tenant_id) as db_session:
                stmt = select(ChatMessage).where(
                    ChatMessage.id == self.message_id,
                    ChatMessage.message_type == MessageType.ASSISTANT,
                )

                chat_message = db_session.execute(stmt).first()

                if not chat_message:
                    await interaction.response.defer()
                    return

                create_chat_message_feedback(
                    is_positive=is_positive,
                    feedback_text="",
                    chat_message_id=chat_message[0].id,
                    user_id=None,
                    db_session=db_session,
                )
                await interaction.response.defer()
        except Exception as e:
            logger.error(f"Database error storing feedback: {e}")
            await interaction.response.defer()
            raise

    @discord.ui.button(emoji="👍", style=discord.ButtonStyle.grey, custom_id="helpful")
    async def helpful_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.process_feedback(interaction, True, "helpful", "not_helpful")

    @discord.ui.button(
        emoji="👎", style=discord.ButtonStyle.grey, custom_id="not_helpful"
    )
    async def not_helpful_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.process_feedback(interaction, False, "helpful", "not_helpful")


class DocumentFeedbackView(BaseFeedbackView):
    def __init__(self, document_id: str, tenant_id: str):
        super().__init__()
        self.document_id = document_id
        self.tenant_id = tenant_id

    async def get_feedback_message(self, is_positive: bool) -> str:
        return (
            "Thanks for the document feedback!"
            if is_positive
            else "Thanks for the feedback. We'll note this document might need improvement!"
        )

    async def handle_feedback(
        self, interaction: discord.Interaction, is_positive: bool
    ):
        try:
            with get_session_with_tenant(self.tenant_id) as db_session:
                feedback_type = (
                    SearchFeedbackType.ENDORSE
                    if is_positive
                    else SearchFeedbackType.REJECT
                )

                create_doc_retrieval_feedback(
                    message_id=None,
                    document_id=self.document_id,
                    document_rank=1,
                    db_session=db_session,
                    clicked=True,
                    feedback=feedback_type,
                )

        except Exception as e:
            logger.error(f"Error storing document feedback: {e}")
            raise

    @discord.ui.button(
        emoji="👍", style=discord.ButtonStyle.grey, custom_id="doc_helpful"
    )
    async def doc_helpful_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.process_feedback(interaction, True, "doc_helpful", "doc_not_helpful")

    @discord.ui.button(
        emoji="👎", style=discord.ButtonStyle.grey, custom_id="doc_not_helpful"
    )
    async def doc_not_helpful_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self.process_feedback(
            interaction, False, "doc_helpful", "doc_not_helpful"
        )


class ContinueOnOnyxView(discord.ui.View):
    def __init__(self, chat_session_id: str, tenant_id: str):
        super().__init__()
        self.add_item(
            discord.ui.Button(
                label="Continue on Onyx",
                style=discord.ButtonStyle.link,
                url=f"https://onyx.app/chat/{chat_session_id}?tenant={tenant_id}",
            )
        )


class StillNeedHelpView(discord.ui.View):
    def __init__(self, users_to_tag: list[str] | None = None):
        super().__init__()
        self.users_to_tag = users_to_tag

    @discord.ui.button(label="Still need help?", style=discord.ButtonStyle.secondary)
    async def still_need_help(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.message.add_reaction("🆘")

        if self.users_to_tag and len(self.users_to_tag) > 0:
            guild = interaction.guild
            if guild:
                mentions = []
                for username in self.users_to_tag:
                    member = discord.utils.get(guild.members, name=username)
                    if member:
                        mentions.append(f"<@{member.id}>")

                if mentions:
                    await interaction.response.send_message(
                        f"{' '.join(mentions)} User needs additional help!"
                    )
                    return

        # If no users to tag or none found, just acknowledge the interaction
        await interaction.response.defer()
