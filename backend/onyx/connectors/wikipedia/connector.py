from typing import ClassVar

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.mediawiki import wiki


class WikipediaConnector(wiki.MediaWikiConnector):
    """Connector for Wikipedia."""

    document_source_type: ClassVar[DocumentSource] = DocumentSource.WIKIPEDIA

    def __init__(
        self,
        categories: list[str],
        pages: list[str],
        recurse_depth: int,
        language_code: str = "en",
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        super().__init__(
            hostname="wikipedia.org",
            categories=categories,
            pages=pages,
            recurse_depth=recurse_depth,
            language_code=language_code,
            batch_size=batch_size,
        )
