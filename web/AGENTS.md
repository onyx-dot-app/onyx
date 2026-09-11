# Frontend Standards

Standards for `web/` and `desktop/`. Every Opal component and layout has a `README.md` beside it.
Read that README instead of guessing props.

## Where components come from

Use, in priority order:

1. `web/lib/opal/src/` (`@opal/*`): the design system.
2. `web/src/refresh-components/`: production components not yet in Opal.
3. `web/src/sections/` (feature composites; entity cards in `sections/cards/`) and `web/src/layouts/`.

Never import from `web/src/components/`. It is legacy and being deleted. The one exception is
`createLogoIcon` in `src/components/icons/icons.tsx`.

- Admin and settings pages: `SettingsLayouts.{Root,Header,Body}` from `@opal/layouts`.
- Icon + title + description: `Content` or `ContentAction` from `@opal/layouts`. Empty states and
  error pages: `IllustrationContent`.
- Buttons: `Button` from `@opal/components`. No raw `<button>`.
- Inputs: Opal or refresh-components. No raw `<input>`, `<textarea>`, or `<select>`.
- Text: `Text` from `@opal/components` with `font` and `color` props. No naked text nodes. The
  boolean-flag API in `refresh-components/texts/Text` is deprecated.
- Icons: only `@opal/icons`. Never `lucide-react` or `react-icons`. If an icon is missing, import
  it from Figma with the Figma MCP tool and add it to `lib/opal/src/icons/`.
- Hover-reveal: `Hoverable` from `@opal/core`. If you must hand-write it, add `no-hover:opacity-100`
  so touch devices still show the item.
- `@opal/core` primitives (`Interactive`, `Disabled`) build components. App code does not use them.

## Rules with a reason

- **No `dark:` Tailwind modifier.** The tokens already define both themes, and overrides break dark
  mode. Only `createLogoIcon` may use it.
- **No built-in Tailwind colors** (`bg-gray-100`, `text-blue-600`). Use the token classes:
  `text-0X`, `background-neutral-0X`, `background-tint-0X`, `border-0X`, `action-selection-0X`,
  `action-danger-0X`, `status-{info,success,warning,error}-0X`, `theme-*`. Tokens live in
  `web/lib/shared/tokens/`.
- **Text props accept markdown.** Type any prop rendered as visible text (`title`, `description`,
  `label`) as `string | RichStr` from `@opal/types` and render it with `Text`. Callers opt in with
  `markdown()` from `@opal/utils`. Plain strings are never parsed.
- **Size props default to `"md"`** when the prop type is `SizeVariants` from `@opal/types` or a
  subset of it.
- **Padding over margin.** Use a component's `padding` prop before wrapping it in a `<div>`. If a
  library component has no such prop, add one to the component instead of adding a wrapper.
- **Data fetching:** `useSWR`, on the client, inside the component that needs the data, with a
  loader while pending. Do not fetch at the top of the page and pass data down.

## Style

- Absolute imports only: `@/` for `src/`, `@opal/` for Opal. No `../` paths.
- Components are `function` declarations, not arrow functions.
- Put the props interface (`FooProps`) in the same file as the component. Put shared types in a
  co-located `types.ts`. `interfaces.ts` is the old name; rename it when you touch one.
- Class names: `cn` from `@opal/utils`, never template strings.
- Hooks: feature hooks go in `web/src/lib/<feature>/hooks.ts`. UI hooks with no app knowledge go
  in Opal. `web/src/hooks/` is the last resort.

## i18n (next-intl)

- No hard-coded user-facing strings under `src/`. The oxlint rule `i18n/no-raw-jsx-text` fails on
  them. Use `useTranslations("<namespace>")` on the client or `await getTranslations(...)` on the
  server.
- `web/src/i18n/messages/en.json` is the source of truth. When you add or change a key, add your
  best translation to every other locale file in that directory. Missing or extra keys fail
  `types:check`. ICU shape must match across locales (`src/i18n/__tests__/catalog.test.ts`).
- Keys are stable identifiers: `<namespace>.<section>.<element>.<role>` in camelCase, for example
  `settings.appearance.colorMode.title`. Rewording the English never changes the key.
- Use ICU for arguments and plurals. Never concatenate translated fragments.
- Dates and numbers: `useFormatter` and `useLocale`, not hard-coded `"en-US"`.
- New styles use logical properties (`ms-`, `pe-`, `start-`) instead of `ml-`, `pr-`, `left-`.

## Tests

- Component tests (Jest + React Testing Library): `web/tests/README.md`.
- E2E (Playwright): `web/tests/e2e/README.md` holds the hard rules (Page Object Model, locator
  priority).
- Run an e2e test with `cd web && bun run playwright <TEST_NAME>`. Do not use `bunx` or `npx`;
  they can fetch an unpinned Playwright.
