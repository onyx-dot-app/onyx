from langchain_core.messages import HumanMessage

from onyx.llm.utils import build_content_with_imgs


IMG_GENERATION_SUMMARY_PROMPT = """
You have just created the attached images in response to the following query: "{query}".

Can you please summarize them in a sentence or two? Do NOT include image urls or bulleted lists.
"""

IMG_GENERATION_SUMMARY_PROMPT_NO_IMAGES = """
You have generated images based on the following query: "{query}".
The prompts used to generate these images were: {prompts}

Describe what the generated images depict based on the query and prompts provided.
Summarize the key elements and content of the images in a sentence or two. Be specific
about what was generated rather than speculating about what the images 'likely' contain.
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
