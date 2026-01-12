from onyx.tools.tool_implementations.open_url.models import WebContent


def filter_web_contents_with_no_title_or_content(
    contents: list[WebContent],
) -> list[WebContent]:
    """Filter out content entries that have neither a title nor any extracted text.

    Some content providers can return placeholder/partial entries that only include a URL.
    Downstream uses these fields for display + prompting; drop empty ones centrally
    rather than duplicating checks across provider clients.
    """
    filtered: list[WebContent] = []
    for content in contents:
        if content.title.strip() or content.full_content.strip():
            filtered.append(content)
    return filtered
