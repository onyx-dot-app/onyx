from langchain_core.messages import HumanMessage

from danswer.llm.utils import build_content_with_imgs


IMG_GENERATION_SUMMARY_PROMPT = """
You have just created the attached images in response to the following query: "{query}".

Can you please summarize them in a sentence or two? Do NOT include image urls or bulleted lists.
"""


def build_image_generation_user_prompt(
    query: str, img_urls: list[str] | None = None
) -> HumanMessage:
    return HumanMessage(
        content=build_content_with_imgs(
            message=IMG_GENERATION_SUMMARY_PROMPT.format(query=query).strip(),
            img_urls=img_urls,
        )
    )
