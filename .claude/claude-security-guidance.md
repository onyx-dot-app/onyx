# Security guidance for Onyx

Additional review rules for this repository. Built-in vulnerability checks
still apply; the rules below are repo-specific and should be treated as
high-signal findings.

## Multi-tenancy

- Onyx is multi-tenant. Database access on per-tenant data must go
  through the tenant-aware SQLAlchemy session that the request/Celery
  middleware sets up; new code paths that obtain a session by other
  means and read tenant data are suspect. Reads from the public schema
  (shared across tenants) must use the public-schema session manager
  instead.
- Celery tasks that touch tenant data must be `TenantAwareTask`s with
  `tenant_id` passed in — that is the mechanism that sets the
  tenant-id contextvar. Do not read tenant state from module-level
  globals or share data across tenants in caches keyed without
  `tenant_id`.
- Redis and the filestore auto-prefix keys/paths with `tenant_id`, but
  only through the known wrappers: new Redis client functions must be
  added to the auto-prefix list, and S3-backed filestore access must
  go through the filestore wrapper (postgres-backed filestores rely on
  schema isolation instead).

## Authentication and authorization

- New FastAPI endpoints that read or mutate user-, chat-, document-, or
  connector-scoped data must declare an auth dependency
  (`current_user`, `current_chat_accessible_user`, `current_admin_user`,
  etc.). Endpoints with no auth dependency must be deliberately public
  and stateless.
- Admin-only operations must use the admin user dependency, not an
  in-handler role check that could be forgotten on a sibling route.
- When loading a resource by ID from the database, verify it belongs to
  the requesting user or tenant before returning it or acting on it
  (no IDOR).

## Credentials and secrets

- Connector credentials must go through the encrypted credential storage
  in `backend/onyx/db/credentials.py`. Do not read or write connector
  credentials as plaintext columns or stash them in unrelated tables.
- Do not log API keys, OAuth tokens or codes, connector credentials,
  session cookies, or full request/response bodies that may contain
  them. Redact before logging, and mask the same values in any error
  message returned to the user.
- Do not embed API keys, OAuth client secrets, or service-account JSON
  in source, tests, fixtures, seed data, or example configs. Tests
  should fetch secrets through `backend/tests/utils/aws_secrets.py`
  rather than reading env vars directly.

## Database and input handling

- Use SQLAlchemy ORM or parameterized queries. Do not interpolate
  user-controlled values into raw SQL with f-strings or `%`-formatting.
- Validate request bodies with Pydantic models at the FastAPI boundary
  before passing values into DB or LLM code.

## Connectors and outbound requests

- Any user-configurable external call (connectors, federated search,
  webhook URLs, OAuth redirect URIs, tool-call HTTP targets, etc.)
  must guard against SSRF: reject requests to private / link-local /
  loopback IP ranges and cloud metadata endpoints unless there is an
  explicit, documented allow-list.
- HTML, Markdown, or rich content fetched from external sources and
  later rendered in the web UI must be sanitized server-side or
  rendered through a sanitizing component.

## Frontend (web/)

- Do not introduce new `dangerouslySetInnerHTML` usages without a
  sanitizer. If sanitizing, the sanitizer must run on every render
  path, not just the happy path.
- Do not echo unsanitized backend strings into URLs passed to
  `window.location`, `router.push`, or anchor `href` attributes
  without validating the scheme.
