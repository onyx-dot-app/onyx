from langchain_core.messages import HumanMessage

from onyx.llm.utils import build_content_with_imgs


IMG_GENERATION_SUMMARY_PROMPT = """
You have just created the attached images in response to the following query: "{query}".

Can you please summarize them in a sentence or two? Do NOT include image urls or bulleted lists.
"""

IMG_GENERATION_SUMMARY_PROMPT_NO_IMAGES = """
You have generated images based on the following query: "{query}".
The prompts used to create these images were: {prompts}

Describe the two images you generated, summarizing the key elements and content in a sentence or two.
Be specific about what was generated and respond as if you have seen them,
without including any disclaimers or speculations.
"""


def build_image_generation_user_prompt(
    query: str,
    supports_image_input: bool,
    img_urls: list[str] | None = None,
    b64_imgs: list[str] | None = None,
    prompts: list[str] | None = None,
) -> HumanMessage:
    if supports_image_input:
        return HumanMessage(
            content=build_content_with_imgs(
                message=IMG_GENERATION_SUMMARY_PROMPT.format(query=query).strip(),
                b64_imgs=b64_imgs,
                img_urls=img_urls,
            )
        )
    else:
        return HumanMessage(
            content=IMG_GENERATION_SUMMARY_PROMPT_NO_IMAGES.format(
                query=query, prompts=prompts
            ).strip()
        )
