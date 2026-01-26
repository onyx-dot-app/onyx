import abc
from collections import defaultdict
from collections.abc import Generator
from collections.abc import Sequence
from contextlib import contextmanager
from unittest.mock import patch

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.db.models import InternetSearchProvider
from onyx.db.web_search import fetch_web_search_provider_by_name
from onyx.tools.tool_implementations.web_search.models import WebSearchProvider
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from shared_configs.enums import WebSearchProviderType


class MockWebSearchResult(BaseModel):
    title: str
    link: str
    snippet: str

    def to_web_search_result(self) -> WebSearchResult:
        return WebSearchResult(
            title=self.title,
            link=self.link,
            snippet=self.snippet,
            author=None,
            published_date=None,
        )


class WebProviderController(abc.ABC):
    @abc.abstractmethod
    def add_results(self, query: str, results: list[MockWebSearchResult]) -> None:
        raise NotImplementedError


class MockWebProvider(WebSearchProvider, WebProviderController):
    def __init__(self) -> None:
        self._results: dict[str, list[MockWebSearchResult]] = defaultdict(list)

    def add_results(self, query: str, results: list[MockWebSearchResult]) -> None:
        self._results[query] = results

    def search(self, query: str) -> Sequence[WebSearchResult]:
        return list(
            map(lambda result: result.to_web_search_result(), self._results[query])
        )

    def test_connection(self) -> dict[str, str]:
        return {}


def add_web_provider_to_db(db_session: Session) -> None:
    # Write a provider to the database
    if fetch_web_search_provider_by_name(name="Test Provider 2", db_session=db_session):
        return

    provider = InternetSearchProvider(
        name="Test Provider 2",
        provider_type=WebSearchProviderType.EXA.value,
        api_key="test-api-key",
        config={},
        is_active=True,
    )

    db_session.add(provider)
    db_session.commit()


def delete_web_provider_from_db(db_session: Session) -> None:
    provider = fetch_web_search_provider_by_name(
        name="Test Provider 2", db_session=db_session
    )
    if provider is not None:
        db_session.delete(provider)
        db_session.commit()


@contextmanager
def use_mock_web_provider(
    db_session: Session,
) -> Generator[WebProviderController, None, None]:
    web_provider = MockWebProvider()

    # Write the tool to the database
    add_web_provider_to_db(db_session)

    # override the build function
    with patch(
        "onyx.tools.tool_implementations.web_search.web_search_tool.build_search_provider_from_config",
        return_value=web_provider,
    ):
        yield web_provider

    delete_web_provider_from_db(db_session)
