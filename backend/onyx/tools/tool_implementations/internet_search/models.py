from pydantic import BaseModel


class InternetSearchResult(BaseModel):
    title: str
    link: str
    snippet: str


class InternetSearchResponse(BaseModel):
    revised_query: str
    internet_results: list[InternetSearchResult]
