# Open URL Fallback And Search Benchmark Implementation Plan

## Issues to Address

`medium` and `deep` search now return richer snippets, but `open_url` still reports a hard failure when the crawler cannot fetch a page. This means the agent may lose useful fallback evidence that was already returned by the preceding `web_search` call. We also need a repeatable way to run real Tavily/Gateway checks without making ordinary unit tests depend on external network availability.

## Important Notes

- `llm_loop` already passes `extract_url_snippet_map(gathered_documents)` into `OpenURLToolOverrideKwargs`.
- `OpenURLTool` already fetches indexed documents and crawled page content in parallel, then merges them.
- The fallback must not pretend a search snippet is full page content. The LLM-facing content should explicitly label it as a recent `web_search` snippet fallback.
- External benchmark runs should be opt-in through environment variables and skipped by default in normal unit test runs.

## Implementation Strategy

- Add a small fallback builder inside `open_url_tool.py` that converts failed URLs with matching `url_snippet_map` entries into `InferenceSection` objects.
- Apply the fallback only after indexed lookup, crawling, and link-based lookup have all failed for that URL.
- Prefer real indexed/crawled content whenever present.
- Remove fallback-resolved URLs from the failure list so `open_url` can return partial usable evidence instead of an all-failed message.
- Add an opt-in external dependency test for the local Gateway using `TAVILY_API_KEY` and `GLOMI_SEARCH_GATEWAY_API_KEY`, covering `medium` and `deep`.

## Tests

- Unit test that a failed URL with a search snippet becomes an `InferenceSection` fallback.
- Unit test that successful crawled content wins over snippet fallback.
- Unit test that snippet fallback removes the URL from failed fetches.
- External dependency test marked `external` / skipped unless required env vars are present; it calls the local Gateway service in-process with Tavily and asserts `medium` / `deep` return result URLs and non-empty snippets.
