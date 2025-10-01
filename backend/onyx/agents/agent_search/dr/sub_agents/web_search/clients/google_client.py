import re
from datetime import datetime

from googleapiclient.discovery import build

from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    InternetSearchInterface,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    InternetSearchResult,
)
from onyx.configs.chat_configs import GOOGLE_SEARCH_API_KEY
from onyx.configs.chat_configs import GOOGLE_SEARCH_CX
from onyx.connectors.cross_connector_utils.miscellaneous_utils import datetime_to_utc
from onyx.utils.retry_wrapper import retry_builder


class GoogleSearchClient(InternetSearchInterface):
    def __init__(
        self, api_key: str = GOOGLE_SEARCH_API_KEY, cx: str = GOOGLE_SEARCH_CX
    ):
        self.cx = cx

        self.service = build("customsearch", "v1", developerKey=api_key)

    @retry_builder(tries=3, delay=1, backoff=2)
    def search(self, query: str) -> list[InternetSearchResult]:
        res = (
            self.service.cse()
            .list(
                q=query,
                cx=self.cx,
                num=10,
            )
            .execute()
        )

        items = res.get("items", [])

        return [
            InternetSearchResult(
                title=item["title"],
                link=item["link"],
                snippet=date_snippet[1],
                author=None,
                published_date=(
                    date_str_to_datetime(date_snippet[0]) if date_snippet[0] else None
                ),
            )
            for item in items
            if (date_snippet := extract_date_and_clean_snippet(item.get("snippet")))
        ]


def extract_date_and_clean_snippet(snippet: str) -> tuple[str, str]:
    """
    Google returns snippets in the format: ?(date ... ) (snippet)
    We want to extract the date and remove it from the snippet
    """
    if not snippet:
        return "", ""

    # Pattern match the date
    # Matches formats like: "Mar 17, 2014 ...", "Sep 14, 2025 ...", "Jul 18, 2013 ..."
    date_pattern = r"^([A-Za-z]{3}\s+\d{1,2},\s+\d{4})\s*\.{3}\s*(.*)$"

    match = re.match(date_pattern, snippet)

    if match:
        extracted_date = match.group(1)
        cleaned_snippet = match.group(2)
        return extracted_date, cleaned_snippet

    return "", snippet


def date_str_to_datetime(date_str: str) -> datetime:
    return datetime_to_utc(datetime.strptime(date_str, "%b %d, %Y"))
