import json
import os
from typing import Any

import litellm

####
# litellm==1.80.11
# openai==2.14.0
####


api_key = os.getenv("OPENAI_API_KEY")

supported_params = litellm.get_supported_openai_params("openai/responses/gpt-5.2")
print(supported_params)

more_supported_params = litellm.get_supported_openai_params("openai/gpt-5.2")
print(more_supported_params)


stream = litellm.completion(
    model="openai/responses/gpt-5.2",
    messages=[
        {
            "role": "system",
            "content": "You are a highly capable, thoughtful, and precise assistant. Your goal is to deeply understand the user's intent, ask clarifying questions when needed, think step-by-step through complex problems, provide clear and accurate answers, and proactively anticipate helpful follow-up information. Always prioritize being truthful, nuanced, insightful, and efficient.\n\nThe current date is Tuesday December 23, 2025.\n\n# Response Style\nYou use different text styles, bolding, emojis (sparingly), block quotes, and other formatting to make your responses more readable and engaging.\nYou use proper Markdown and LaTeX to format your responses for math, scientific, and chemical formulas, symbols, etc.: '$$\\n[expression]\\n$$' for standalone cases and '\\( [expression] \\)' when inline.\nFor code you prefer to use Markdown and specify the language.\nYou can use horizontal rules (---) to separate sections of your responses.\nYou can use Markdown tables to format your responses for data, lists, and other structured information.\n\n\n# User Information\n\nThe user is at an organization called `Onyx`.\n\nOrganization description: AI chat and enterprise search. Open source, self host or managed cloud.\n\nGithub: https://github.com/onyx-dot-app/onyx\nWebsite: https://onyx.app\n\n- User's name: Wenxi\n- User's email: wenxi@onyx.app\n\n# Tools\n\nFor questions that can be fully answered from existing knowledge which is unlikely to change, answer the user directly without using any tools. When there is ambiguity, default to searching to get more context.\n\nWhen using any search type tool, do not make any assumptions and stay as faithful to the user's query as possible. Between internal and web search, think about if the user's query is likely better answered by team internal sources or online web pages. For queries that are short phrases, ambiguous/unclear, or keyword heavy, prioritize internal search. If ambiguious, prioritize internal search.\nWhen searching for information, if the initial results cannot fully answer the user's query, try again with different tools or arguments. Do not repeat the same or very similar queries if it already has been run in the chat history.\n\n\n## internal_search\nUse the `internal_search` tool to search connected applications for information. Some examples of when to use `internal_search` include:\n- Internal information: any time where there may be some information stored in internal applications that could help better answer the query.\n- Niche/Specific information: information that is likely not found in public sources, things specific to a project or product, team, process, etc.\n- Keyword Queries: queries that are heavily keyword based are often internal document search queries.\n- Ambiguity: questions about something that is not widely known or understood.\nNever provide more than 3 queries at once to `internal_search`.\n\n\n## web_search\nUse the `web_search` tool to access up-to-date information from the web. Some examples of when to use `web_search` include:\n- Freshness: if up-to-date information on a topic could change or enhance the answer. Very important for topics that are changing or evolving.\n- Niche Information: detailed info not widely known or understood (but that is likely found on the internet).\n- Accuracy: if the cost of outdated information is high, use web sources directly.\n\n\n## open_url\nUse the `open_url` tool to read the content of one or more URLs. Use this tool to access the contents of the most promising web pages from your searches.\nYou can open many URLs at once by passing multiple URLs in the array if multiple pages seem promising. Prioritize the most promising pages and reputable sources.\nYou should almost always use open_url after a web_search call. Use this tool when a user asks about a specific provided URL.\n\n\n## generate_image\nNEVER use generate_image unless the user specifically requests an image.\n",
        },
        # {
        #     "role": "user",
        #     "content": "how would you convert a python react monorepo to rust and svlete? make sure to create a comprehensive plan and list all the steps you would take.",
        # },
        # {
        #     "role": "assistant",
        #     "content": "Below is a **comprehensive, end-to-end migration plan** to convert a **Python + React monorepo** into **Rust (backend) + Svelte/SvelteKit (frontend)**. It’s written to support an **incremental “strangler-fig” migration** (run old and new side-by-side) so you can ship continuously and reduce risk.\n\n---\n\n## 0) Clarify scope + lock requirements (do this first)\nBefore touching code, answer these (they materially change the plan):\n\n1. **Python backend framework**: Django? FastAPI? Flask? Celery?  \n2. **API style**: REST (OpenAPI), GraphQL, gRPC, websockets, SSE?\n3. **Auth**: sessions/cookies, JWT, OAuth/OIDC (Auth0/Keycloak), SSO?\n4. **DB and data layer**: Postgres/MySQL, Redis, Elasticsearch, vector DB, etc.\n5. **Background work**: Celery/RQ/cron? queues? exactly-once requirements?\n6. **Frontend**: CSR vs SSR today; React Router/Next.js; state mgmt (Redux/Zustand)?\n7. **Deployment**: K8s, ECS, Docker Compose, serverless; observability stack?\n8. **Monorepo tooling**: Nx/Turborepo/pnpm/yarn; CI provider; code owners?\n\n**Output of this phase**: a 1–3 page migration spec that defines success criteria, risk areas, and the incremental cutover strategy.\n\n---\n\n## 1) Repository + architecture target (design the end state)\n### 1.1 Choose Rust backend stack (pick one primary path)\nCommon choices:\n\n- **Axum + Tokio** (modern, flexible, great ecosystem)\n- **Actix-web** (very fast, mature, slightly different ergonomics)\n- **Warp** (solid but Axum has become more common)\n\nData layer options:\n- **sqlx** (async, compile-time checked SQL, excellent for Postgres)\n- **Diesel** (ORM-ish; strong typing, but heavier)\n- **SeaORM** (async ORM)\n\nAPI contracts:\n- REST: **OpenAPI** via `utoipa` / `axum` integrations  \n- gRPC: `tonic`  \n- GraphQL: `async-graphql`",
        # },
        {"role": "user", "content": "hi?"},
    ],
    api_key=api_key,
    tools=[
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for information. Returns a list of search results with titles, metadata, and snippets.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "queries": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "One or more queries to look up on the web.",
                        }
                    },
                    "required": ["queries"],
                },
            },
        }
    ],
    tool_choice="required",
    stream=True,
    temperature=1,
    timeout=600,
    max_tokens=None,
    stream_options={"include_usage": True},
    parallel_tool_calls=True,
    reasoning_effort="high",
    allowed_openai_params=["tool_choice"],
)

# stream = litellm.responses(
#     model="openai/gpt-5.2",
#     #input="how would you convert a python react monorepo to rust and svlete? make sure to create a comprehensive plan and list all the steps you would take.",
#     input="hi",
#     tools=[
#         {
#             "name": "onyx_web_search",
#             "type": "function",
#             "description": "Search the web for information. Returns a list of search results with titles, metadata, and snippets.",
#             "parameters": {
#                 "type": "object",
#                 "properties": {
#                     "queries": {
#                         "type": "array",
#                         "items": {"type": "string"},
#                         "description": "One or more queries to look up on the web.",
#                     }
#                 },
#                 "required": ["queries"],
#             },
#         }
#     ],
#     tool_choice="required",
#     stream=True,
#     temperature=1,
#     timeout=600,
#     # Responses API uses `max_output_tokens` (omit when unset, instead of passing `max_tokens=None`)
#     parallel_tool_calls=True,
#     reasoning={"effort": "high"},
# )


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _to_jsonable(x: Any) -> Any:
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    if isinstance(x, dict):
        return {k: _to_jsonable(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_to_jsonable(v) for v in x]
    if hasattr(x, "model_dump"):
        return _to_jsonable(x.model_dump())
    if hasattr(x, "dict"):
        try:
            return _to_jsonable(x.dict())
        except Exception:
            pass
    return str(x)


for event in stream:
    # Pure raw output: one JSON blob per stream event.
    print(json.dumps(_to_jsonable(event), ensure_ascii=False), flush=True)
