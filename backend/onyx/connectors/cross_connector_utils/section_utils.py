from typing import TypeVar

from onyx.configs.app_configs import CONNECTOR_MAX_EXTRACTED_TEXT_CHARS
from onyx.connectors.models import ImageSection, Section
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Preserves the caller's section union: `list` is invariant, so a connector
# that only builds text/image sections cannot pass a list typed for the full
# document union.
SectionT = TypeVar("SectionT", bound=Section)


def cap_sections_text(
    sections: list[SectionT],
    file_name: str | None,
) -> list[SectionT]:
    """Bound the total text retained per file to bound connector worker memory.
    Needed when a source can't be size-checked before fetch (e.g. Google-native
    files report no `size` metadata). A non-positive cap disables."""
    if CONNECTOR_MAX_EXTRACTED_TEXT_CHARS <= 0:
        return sections

    remaining = CONNECTOR_MAX_EXTRACTED_TEXT_CHARS
    for i, section in enumerate(sections):
        if isinstance(section, ImageSection):
            continue
        if section.text is None:
            # File-backed (e.g. streamed TabularSection) — content lives in the
            # file store and is already bounded; nothing inline to cap.
            continue
        if len(section.text) > remaining:
            logger.warning(
                "Extracted text for %s exceeds %s chars. Truncating.",
                file_name,
                CONNECTOR_MAX_EXTRACTED_TEXT_CHARS,
            )
            capped = sections[:i]
            if remaining > 0:
                capped.append(
                    section.model_copy(update={"text": section.text[:remaining]})
                )
            return capped
        remaining -= len(section.text)
    return sections
