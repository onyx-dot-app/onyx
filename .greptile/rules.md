# Greptile Review Rules

## Type Annotations

Use explicit type annotations for variables to enhance code clarity, especially when moving type hints around in the code.

## Best Practices

Use the "Engineering Best Practices" section of `CONTRIBUTING.md` as core review context. Prefer consistency with existing patterns, fix issues in code you touch, avoid tacking new features onto muddy interfaces, fail loudly instead of silently swallowing errors, keep code strictly typed, preserve clear state boundaries, remove duplicate or dead logic, break up overly long functions, avoid hidden import-time side effects, respect module boundaries, and favor correctness-by-construction over relying on callers to use an API correctly.

## TODOs

Whenever a TODO is added, there must always be an associated name or ticket with that TODO in the style of `TODO(name): ...` or `TODO(1234): ...`

## Debugging Code

Remove temporary debugging code before merging to production, especially tenant-specific debugging logs.

## Hardcoded Booleans

When hardcoding a boolean variable to a constant value, remove the variable entirely and clean up all places where it's used rather than just setting it to a constant.

## Multi-tenant vs Single-tenant

Code changes must consider both multi-tenant and single-tenant deployments. In multi-tenant mode, preserve tenant isolation, ensure tenant context is propagated correctly, and avoid assumptions that only hold for a single shared schema or globally shared state. In single-tenant mode, avoid introducing unnecessary tenant-specific requirements or cloud-only control-plane dependencies.

## Routing for New Non-/api Backend Routes

Whenever a new backend route is added that does NOT start with `/api`, it must be explicitly routed in ALL nginx configs:

- `deployment/helm/charts/onyx/templates/nginx-conf.yaml` (Helm/k8s, bundled nginx)
- `deployment/data/nginx/app.conf.template` (docker-compose dev)
- `deployment/data/nginx/app.conf.template.prod` (docker-compose prod)
- `deployment/data/nginx/app.conf.template.no-letsencrypt` (docker-compose no-letsencrypt)

Routes not starting with `/api` are not caught by the existing `^/(api|openapi\.json)` location block and will fall through to `location /`, which proxies to the Next.js web server and returns an HTML 404. In the nginx configs, the new location block must be placed before the `/api` block. Examples of routes that need this treatment: `/scim`, `/mcp`.

The route must ALSO be covered in Helm ingress mode (`ingress.enabled=true`), which does not use the bundled nginx. Add a dedicated ingress template for the route (see `deployment/helm/charts/onyx/templates/ingress-scim.yaml`). `ingress-api.yaml` cannot host it, since that resource only routes `/api` and its resource-wide rewrite annotation strips other prefixes. If the web app owns a sub-path of the route (for example an IdP callback page), carve that sub-path back out to the webserver with `pathType: Exact`, following `ingress-mcp-oauth-callback.yaml`.

## Backend API Consumers Beyond the Web App

The backend HTTP API is not consumed only by `web/`. Changing a route path, its request or response model, or its auth requirements is a breaking change for consumers that no frontend build or type check will catch:

- `backend/onyx/mcp_server/` — MCP tools and resources call the API over HTTP, forwarding the caller's bearer token, and parse responses with the backend's own Pydantic models. A renamed or removed field breaks them at runtime, not at build time.
- `terraform-provider-onyx/internal/client/` — a Go client with hand-written request and response structs. It depends heavily on **admin** routes (`/admin/api-key`, `/admin/persona`, `/manage/admin/connector`, `/manage/admin/cc-pair`, `/manage/admin/document-set`, `/manage/admin/user-group`) as well as non-admin ones like `/persona`. "This is only an admin endpoint" is not a reason to treat a change as safe.
- `mobile/` and `desktop/`.
- External customers calling the API directly with a Personal Access Token or API key.

When a change touches a route or a model it returns, check whether these consumers reference the path before treating the change as web-only. Prefer additive changes: adding an optional field is safe, renaming or removing one is not.

Routes tagged `PUBLIC_API_TAGS` are a published contract. `backend/scripts/transform_openapi_for_docs.py` filters on the `public` tag to build the customer-facing API documentation, so those paths, parameters and response fields are visible to customers and should only change additively.

Any route intended to be reachable programmatically must declare an auth marker: either `Depends(require_permission(...))` or `dependencies=[Depends(scope_exempt)]`. `_scoped_pat_permitted_on_route` in `backend/onyx/auth/users.py` fails closed — a route whose auth dependency carries neither marker rejects scoped Personal Access Tokens with `INSUFFICIENT_PERMISSIONS`, while still working with a session cookie or an unscoped token. This is easy to miss, because the web app only ever authenticates with a session.

## Full vs Lite Deployments

Code changes must consider both regular Onyx deployments and Onyx lite deployments. Lite deployments disable the vector DB, Redis, model servers, and background workers by default, use PostgreSQL-backed cache/auth/file storage, and rely on the API server to handle background work. Do not assume those services are available unless the code path is explicitly limited to full deployments.

## LLM Call Tagging — Always Use LLMFlow Registry

Every LLM, embedding, rerank, image-generation, voice (STT/TTS), and intent-classification call must open a generation span tagged with a value from the `LLMFlow` registry in `backend/onyx/tracing/flows.py`. Use `llm_generation_span(llm=..., flow=LLMFlow.X, ...)` for calls going through an `LLM` subclass, or `traced_llm_call(flow=LLMFlow.X, model=..., provider=..., ...)` for direct provider SDK / `litellm` / model_server HTTP calls that bypass the `LLM` abstraction. Never pass raw strings to `flow=` — add a new `LLMFlow` enum value first. Flow tags name the operation (e.g. `IMAGE_EDIT`, `RERANK`), not the provider; provider goes in `model_config["model_provider"]`. The auto-wrap fallback emits `LLMFlow.UNTAGGED_INVOKE` / `UNTAGGED_STREAM` for missing instrumentation — those sentinels are a signal to fix the call site, not a substitute for explicit tagging.

## SWR Cache Keys — Always Use SWR_KEYS Registry

All `useSWR()` calls and `mutate()` calls in the frontend must reference the centralized `SWR_KEYS` registry in `web/src/lib/swr-keys.ts` instead of inline endpoint strings or local string constants. Never write `useSWR("/api/some/endpoint", ...)` or `mutate("/api/some/endpoint")` — always use the corresponding `SWR_KEYS.someEndpoint` constant. If the endpoint does not yet exist in the registry, add it there first. This applies to all variants of an endpoint (e.g. query-string variants like `?get_editable=true` must also be registered as their own key).

## Playwright E2E — Page Object Model

All tests under `web/tests/e2e/` must drive the UI through Page Object classes (e.g. `ChatPage`, `InputBar`). Locators and interactions for a surface live on the page object; specs call methods like `chatPage.inputBar.someMethod()` and do not construct locators inline. When extending coverage for an area that has no page object, create one before writing the spec. See `web/tests/e2e/README.md`.

## Playwright E2E — Auto-Retrying Matchers Only

Never use `locator.getAttribute()`, `locator.textContent()`, `locator.count()`, or `page.evaluate()` snapshots as the basis of an assertion on state that may update asynchronously (React state, effects, microtasks, deferred DOM mutations). One-shot reads flake. Use Playwright's auto-retrying matchers: `expect(locator).toHaveAttribute(...)`, `toHaveClass(...)`, `toHaveText(...)` / `toContainText(...)`, `toHaveCount(...)`, `toHaveValue(...)`, `toBeVisible()` / `toBeHidden()`. Snapshot reads are still fine when the value drives control flow inside the spec — not for assertions. See `web/tests/e2e/README.md`.
