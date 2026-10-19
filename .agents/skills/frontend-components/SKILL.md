---
name: frontend-components
description: Find the existing Opal or refresh-components component before you build UI in web/. Use it whenever you design, build or change a page, view, modal, form, card, list, empty state or any other UI in web/, and before you create a new .tsx component.
---

# Frontend components

Build Onyx UI from the components that exist. Do not design a component from scratch when the
design system has one. `CATALOG.md` next to this file lists every Opal component and layout and
every refresh-component, with its import and a one-line purpose.

## Procedure

1. Read `CATALOG.md`.
2. List the UI pieces the task needs: page shell, header, rows, cards, buttons, inputs, menus,
   empty states, loaders and text.
3. Match each piece to a catalog entry. Use this order:
   1. Opal components and layouts (`@opal/components`, `@opal/layouts`).
   2. refresh-components, only when Opal has no match. Never use a row marked **Replaced**.
   3. Feature composites in `web/src/sections/` and `web/src/layouts/`. Search them with `rg`.
4. Read the README.md of each Opal component you use. The Docs column gives its path. Do not
   guess props.
5. For design work, write the map from piece to component before you write code. Put it in the
   plan or in your reply.
6. Build a new component only when nothing matches. Say which pieces had no match and why. Put a
   reusable new component in Opal, not in the feature folder.

## Migrate on touch

When you edit a file, migrate its refresh-components imports that Opal replaces. oxlint rule
`opal/no-replaced-refresh-import` names them, and the `opal_migrate_on_edit.py` hook reports them to
the agent after each edit. Keep the behavior the same.

## Keep the catalog current

The catalog is generated. After you add, rename or delete a component, or change the first
paragraph of an Opal README, run:

```bash
python3 .agents/skills/frontend-components/generate_catalog.py
```

The `frontend-component-catalog` pre-commit hook fails when the catalog is out of date.

The other frontend rules (tokens, icons, text, i18n) are in `web/AGENTS.md`.
