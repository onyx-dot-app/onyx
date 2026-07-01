# Skills — Docs Index

Authoritative docs for the Skills feature live at this directory's top level.
Older planning material has been removed from the active docs; use the files
below as the source of truth.

## Authoritative (read in this order)

1. `skills-requirements.md` — what V1 must do. Concept, bundle format, data model, visibility, sandbox-delivery model (push via `SandboxManager`), API surface, non-requirements, open questions.
2. `skills-db-layer-status.md` — snapshot of the DB layer already shipped on `whuang/skills-api`: tables, CRUD module, built-in registry, bundle validator, migration.
3. `skills-api-plan.md` — implementation plan for the FastAPI layer that exposes the DB primitives. Routes, Pydantic models, write-path interface, tests, subagent decomposition.
4. `personal-skills.md` — the user-managed (personal) skills slice built on top of the admin feature: derived "personal" predicate, user API surface, ownership gating, per-user cap, promotion lifecycle, frontend, tests, and decisions/open questions for future work.
