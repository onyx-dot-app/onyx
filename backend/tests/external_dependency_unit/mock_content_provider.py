import abc
from collections.abc import Generator
from collections.abc import Sequence
from contextlib import contextmanager
from unittest.mock import patch

from pydantic import BaseModel

from onyx.tools.tool_implementations.open_url.models import WebContent
from onyx.tools.tool_implementations.open_url.models import WebContentProvider


class MockWebContent(BaseModel):
    title: str
    url: str
    content: str

    def to_web_content(self) -> WebContent:
        return WebContent(
            title=self.title,
            link=self.url,
            full_content=self.content,
            published_date=None,
            scrape_successful=True,
        )


class ContentProviderController(abc.ABC):
    @abc.abstractmethod
    def add_content(self, content: MockWebContent) -> None:
        raise NotImplementedError


class MockContentProvider(WebContentProvider, ContentProviderController):
    def __init__(self) -> None:
        self._contents: list[MockWebContent] = []

    def add_content(self, web_content: MockWebContent) -> None:
        self._contents.append(web_content)

    def contents(self, urls: Sequence[str]) -> list[WebContent]:
        filtered_contents = list(
            filter(lambda web_content: web_content.url in urls, self._contents)
        )

        return list(
            map(lambda web_content: web_content.to_web_content(), filtered_contents)
        )


@contextmanager
def use_mock_content_provider() -> Generator[ContentProviderController, None, None]:
    content_provider = MockContentProvider()

    with patch(
        "onyx.tools.tool_implementations.open_url.open_url_tool.get_default_content_provider",
        return_value=content_provider,
    ):
        yield content_provider
