# Greptile Review Rules

## Type Annotations

Use explicit type annotations for variables to enhance code clarity, especially when moving type hints around in the code.

## Best Practices

Use `contributing_guides/best_practices.md` as core review context. Prefer consistency with existing patterns, fix issues in code you touch, avoid tacking new features onto muddy interfaces, fail loudly instead of silently swallowing errors, keep code strictly typed, preserve clear state boundaries, remove duplicate or dead logic, break up overly long functions, avoid hidden import-time side effects, respect module boundaries, and favor correctness-by-construction over relying on callers to use an API correctly.

## TODOs

Whenever a TODO is added, there must always be an associated name or ticket with that TODO in the style of `TODO(name): ...` or `TODO(1234): ...`

## Debugging Code

Remove temporary debugging code before merging to production, especially tenant-specific debugging logs.

## Hardcoded Booleans

When hardcoding a boolean variable to a constant value, remove the variable entirely and clean up all places where it's used rather than just setting it to a constant.

## Multi-tenant vs Single-tenant

Code changes must consider both multi-tenant and single-tenant deployments. In multi-tenant mode, preserve tenant isolation, ensure tenant context is propagated correctly, and avoid assumptions that only hold for a single shared schema or globally shared state. In single-tenant mode, avoid introducing unnecessary tenant-specific requirements or cloud-only control-plane dependencies.

## Full vs Lite Deployments

Code changes must consider both regular Onyx deployments and Onyx lite deployments. Lite deployments disable the vector DB, Redis, model servers, and background workers by default, use PostgreSQL-backed cache/auth/file storage, and rely on the API server to handle background work. Do not assume those services are available unless the code path is explicitly limited to full deployments.
