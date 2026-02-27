# Engineering Principles, Style, and Correctness Guide

## Principles and collaboration

- **Use 1-way vs 2-way doors.** For 2-way doors, move faster and iterate. For 1-way doors, be more deliberate.
- **Consistency > being “right.”** Prefer consistent patterns across the codebase. If something is truly bad, fix it everywhere.
- **Fix what you touch (selectively).**
  - Don’t feel obligated to fix every best-practice issue you notice.
  - Don’t introduce new bad practices.
  - If your change touches code that violates best practices, fix it as part of the change.
- **Don’t tack features on.** When adding functionality, restructure logically as needed to avoid muddying interfaces and accumulating tech debt.

---

## Style and maintainability

### Comments and readability
Add clear comments:
- At logical boundaries (e.g., interfaces) so the reader doesn’t need to dig 10 layers deeper.
- Wherever assumptions are made or something non-obvious/unexpected is done.
- For complicated flows/functions.
- Wherever it saves time (e.g., nontrivial regex patterns).

### Errors and exceptions
- **Fail loudly** rather than silently skipping work.
  - Example: raise and let exceptions propagate instead of silently dropping a document.
- **Don’t overuse `try/except`.**
  - Put `try/except` at the correct logical level.
  - Do not mask exceptions unless it is clearly appropriate.

### Typing
- Everything should be **as strictly typed as possible**.
- Use `cast` for annoying/loose-typed interfaces (e.g., results of `run_functions_tuples_in_parallel`).
  - Only `cast` when the type checker sees `Any` or types are too loose.
- Prefer types that are easy to read.
  - Avoid dense types like `dict[tuple[str, str], list[list[float]]]`.
  - Prefer domain models, e.g.:
    - `EmbeddingModel(provider_name, model_name)` as a Pydantic model
    - `dict[EmbeddingModel, list[EmbeddingVector]]`

### State, objects, and boundaries
- Keep **clear logical boundaries** for state containers and objects.
- A **config** object should never contain things like a `db_session`.
- Avoid state containers that are:
  - overly nested, or
  - huge + flat (use judgment).
- Prefer **composition and functional style** over inheritance/OOP.
- Prefer **no mutation** unless there’s a strong reason.
- State objects should be **intentional and explicit**, ideally nonmutating.
- Use interfaces/objects to create clear separation of responsibility.
- Prefer simplicity when there’s no clear gain
  - Avoid overcomplicated mechanisms like semaphores.
  - Prefer **hash maps (dicts)** over tree structures unless there’s a strong reason.

### Naming
- Name variables carefully and intentionally.
- Prefer long, explicit names when undecided.
- Avoid single-character variables except for small, self-contained utilities (or not at all).
- Keep the same object/name consistent through the call stack and within functions when reasonable.
  - Good: `for token in tokens:`
  - Bad: `for msg in tokens:` (if iterating tokens)
- Function names should bias toward **long + descriptive** for codebase search.
  - IntelliSense can miss call sites; search works best with unique names.
  - “Fetch versioned implementation” is an example of why this matters.

### Correctness by construction
- Prefer self-contained correctness.
  - Don’t rely on callers to “use it right” if you can make misuse hard.
- Avoid redundancies:
  - If a function takes an arg, it shouldn’t also take a state object that contains that same arg.
- No dead code (unless there’s a very good reason).
- No commented-out code in main or feature branches (unless there’s a very good reason).
- No duplicate logic:
  - Don’t copy/paste into branches when shared logic can live above the conditional.
  - If you’re afraid to touch the original, you don’t understand it well enough.
  - LLMs often create subtle duplicate logic—review carefully and remove it.
  - Avoid “nearly identical” objects that confuse when to use which.
- Avoid extremely long functions with chained logic:
  - Encapsulate steps into helpers for readability, even if not reused.
  - “Pythonic” multi-step expressions are OK in moderation; don’t trade clarity for cleverness.

---

## Performance and correctness

- Avoid holding resources for extended periods:
  - DB sessions
  - locks/semaphores
- Validate objects:
  - on creation, and
  - right before use.
- Connector code (data → Onyx documents):
  - Any in-memory structure that can grow without bound based on input must be periodically size-checked.
  - If a connector is OOMing (often shows up as “missing celery tasks”), this is a top thing to check retroactively.

---

## Repository conventions: where code lives

- Pydantic + data models: `models.py` files.
- DB interface functions (excluding lazy loading): `db/` directory.
- LLM prompts: `prompts/` directory, roughly mirroring the code layout that uses them.
- API routes: `server/` directory.

---

## Pydantic and modeling rules

- Prefer **Pydantic** over dataclasses.
- If absolutely required, use `allow_arbitrary_types`.

---

## Data conventions

- Prefer explicit `None` over sentinel empty strings (usually; depends on intent).
- Prefer explicit identifiers:
  - Use string enums instead of integer codes.
- Avoid magic numbers (co-location is good when necessary). **Always avoid magic strings.**

---

## Logging

- Log messages where they are created.
- Don’t propagate log messages around just to log them elsewhere.

---

## Encapsulation

- Don’t use private attributes/methods/properties from other classes/modules.
- “Private” is private—respect that boundary.

---

## SQLAlchemy guidance

- Lazy loading is often bad at scale, especially across multiple list relationships.
- Be careful when accessing SQLAlchemy object attributes:
  - It can help avoid redundant DB queries,
  - but it can also fail if accessed outside an active session,
  - and lazy loading can add hidden DB dependencies to otherwise “simple” functions.
- Reference: https://www.reddit.com/r/SQLAlchemy/comments/138f248/joinedload_vs_selectinload/

---

## Trunk-based development and feature flags

- **PRs should contain no more than 500 lines of real change.**
- **Merge to main frequently.** Avoid long-lived feature branches—they create merge conflicts and integration pain.
- **Use feature flags for incremental rollout.**
  - Large features should be merged in small, shippable increments behind a flag.
  - This allows continuous integration without exposing incomplete functionality.
- **Keep flags short-lived.** Once a feature is fully rolled out, remove the flag and dead code paths promptly.
- **Flag at the right level.** Prefer flagging at API/UI entry points rather than deep in business logic.
- **Test both flag states.** Ensure the codebase works correctly with the flag on and off.

---

## Misc

- Any TODOs you add in the code must be accompanied by either the name/username
  of the owner of that TODO, or an issue number for an issue referencing that
  piece of work.
- Avoid module-level logic that runs on import, which leads to import-time side
  effects. Essentially every piece of meaningful logic should exist within some
  function that has to be explicitly invoked. Acceptable exceptions to this may
  include loading environment variables or setting up loggers.
  - If you find yourself needing something like this, you may want that logic to
    exist in a file dedicated for manual execution (contains `if __name__ ==
    "__main__":`) which should not be imported by anything else.
- Related to the above, do not conflate Python scripts you intend to run from
  the command line (contains `if __name__ == "__main__":`) with modules you
  intend to import from elsewhere. If for some unlikely reason they have to be
  the same file, any logic specific to executing the file (including imports)
  should be contained in the `if __name__ == "__main__":` block.
  - Generally these executable files exist in `backend/scripts/`.
