# Greptile Review Context

## Type Annotations

Use explicit type annotations for variables to enhance code clarity, especially when moving type hints around in the code.

## Best Practices

Use `contributing_guides/best_practices.md` as core review context. Prefer consistency with existing patterns, fix issues in code you touch, avoid tacking new features onto muddy interfaces, fail loudly instead of silently swallowing errors, keep code strictly typed, preserve clear state boundaries, remove duplicate or dead logic, break up overly long functions, avoid hidden import-time side effects, respect module boundaries, and favor correctness-by-construction over relying on callers to use an API correctly.
