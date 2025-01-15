from langchain_core.messages import HumanMessage

from onyx.file_store.models import ChatFileType
from onyx.file_store.models import InMemoryChatFile
from onyx.llm.utils import build_content_with_imgs


CUSTOM_IMG_GENERATION_SUMMARY_PROMPT = """
You have just created the attached {file_type} file in response to the following query: "{query}".

Can you please summarize it in a sentence or two? Do NOT include image urls or bulleted lists.
"""


def build_custom_image_generation_user_prompt(
    query: str, file_type: ChatFileType, files: list[InMemoryChatFile] | None = None
) -> HumanMessage:
    return HumanMessage(
        content=build_content_with_imgs(
            message=CUSTOM_IMG_GENERATION_SUMMARY_PROMPT.format(
                query=query, file_type=file_type.value
            ).strip(),
            files=files,
        )
    )
