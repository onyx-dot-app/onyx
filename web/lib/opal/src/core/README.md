# Core

The lowest-level primitives of the Opal design system. Think of `core` like Rust's `core` crate — compiler intrinsics and foundational types — while higher-level modules (like Rust's `std`) provide the public-facing components that most consumers should reach for first.

End-users *can* use these components directly when needed, but in most cases they should prefer the higher-level components (such as `Button`, `OpenButton`, etc.) that are built on top of `core`.

## Contents

| Primitive | Description | Docs |
|-----------|-------------|------|
| [Interactive](./interactive/) | Foundational hover/active/disabled/selected state styling | [README](./interactive/README.md) |
