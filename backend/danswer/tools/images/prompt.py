from langchain_core.messages import HumanMessage

from danswer.llm.utils import build_content_with_imgs


NON_TOOL_CALLING_PROMPT = """
You have just created the attached images in response to the following query: "{{query}}".

Can you please summarize them in a sentence or two?
"""

TOOL_CALLING_PROMPT = """
Can you please summarize the two images you generate in a sentence or two?
"""


def build_image_generation_user_prompt(
    query: str, img_urls: list[str] | None = None
) -> HumanMessage:
    if img_urls:
        return HumanMessage(
            content=build_content_with_imgs(
                message=NON_TOOL_CALLING_PROMPT.format(query=query).strip(),
                img_urls=img_urls,
            )
        )

    return HumanMessage(
        content=build_content_with_imgs(
            message=TOOL_CALLING_PROMPT.strip(),
            img_urls=img_urls,
        )
    )
