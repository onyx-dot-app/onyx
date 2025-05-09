from pydantic import BaseModel


class InternetSearchResult(BaseModel):
    title: str
    url: str
    published_date: str
    author: str | None
    score: float | None
    full_content: str | None
    relevant_content: str
    summary: str


class InternetSearchResponse(
    BaseModel
):  # TODO: rewrite this to be closer to search tool SearchResponseSummary
    revised_query: str
    internet_results: list[InternetSearchResult]
