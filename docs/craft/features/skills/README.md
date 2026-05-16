# Skills — Docs Index

Authoritative docs for the Skills feature live at this directory's top level. Older planning material is in `archive/` and should not be used as an implementation reference.

## Authoritative (read in this order)

1. `skills-requirements.md` — what V1 must do. Concept, bundle format, data model, visibility, sandbox-delivery model (push via `SandboxManager`), API surface, non-requirements, open questions.
2. `skills-db-layer-status.md` — snapshot of the DB layer already shipped on `whuang/skills-api`: tables, CRUD module, built-in registry, bundle validator, migration.
3. `skills-api-plan.md` — implementation plan for the FastAPI layer that exposes the DB primitives. Routes, Pydantic models, write-path interface, tests, subagent decomposition.

## Archived (`archive/`)

- `skills.md` — original design doc; superseded by `skills-requirements.md`.
- `skills_plan.md` — long PRD / implementation spec; superseded by `skills-requirements.md` + `skills-api-plan.md`. Its sandbox-delivery design (per-session materialization + push pipeline) has been replaced by the `SandboxManager` push API model.
- `skills_plan.html` — HTML render of `skills_plan.md`; archived alongside it.
- `sandbox-file-sync.md` — push-pipeline / tarball / kubectl-exec delivery design; superseded by the `SandboxManager` push API model in `skills-requirements.md` §5.
- `TODOS.md` — task board against the old design. Most tasks are stale; the new docs are the forward-looking source of truth.
