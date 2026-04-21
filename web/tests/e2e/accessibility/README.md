# Accessibility Tests

Automated accessibility (a11y) testing for the Onyx frontend using
[axe-core](https://github.com/dequelabs/axe-core) via
[@axe-core/playwright](https://github.com/dequelabs/axe-core-npm/tree/develop/packages/playwright).

## How it works

axe-core is the industry-standard accessibility rules engine maintained by Deque Systems.
`@axe-core/playwright` injects it into a live Playwright browser page and evaluates the
rendered DOM against WCAG success criteria. Every violation includes the rule ID, impact
level, affected elements, and a link to remediation guidance.

Tests target **WCAG 2.1 Level AA** by default — the conformance level required by most
accessibility regulations (ADA, Section 508, EN 301 549).

## Strict vs. warning mode (the ratchet)

Not all violations fail CI immediately. The system uses a **ratchet** — rules graduate
from warning to strict as they are fixed:

- **Warning rules** (default): violations are logged as test annotations visible in the
  Playwright HTML report, but the test passes. This gives visibility without blocking PRs.
- **Strict rules**: violations fail the test. Once a rule has zero violations across the
  entire app, it gets added to `STRICT_RULES` in `utils/accessibility.ts`. CI then
  prevents regressions.

The ratchet only tightens — once a rule is strict, it stays strict.

### Promoting a rule to strict

1. Fix all instances of the rule across the app (e.g. add `aria-label` to every icon-only
   button for `button-name`).
2. Add the rule ID to `STRICT_RULES` in `tests/e2e/utils/accessibility.ts`:
   ```ts
   export const STRICT_RULES: string[] = [
     "button-name",
   ];
   ```
3. Run the tests to confirm zero violations for that rule.
4. Merge. CI now blocks any PR that reintroduces that violation.

## Directory structure

```
accessibility/
├── README.md                  # You are here
├── public_pages.spec.ts       # Unauthenticated pages (login, signup)
├── app_pages.spec.ts          # Core authenticated pages (chat, search)
├── admin_pages.spec.ts        # All admin pages (auto-discovered from sidebar)
└── settings_pages.spec.ts     # All settings tabs (auto-discovered from nav)

utils/
└── accessibility.ts           # scanAccessibility(), STRICT_RULES, formatViolations()

fixtures/
└── accessibility.ts           # Playwright fixture: expectAccessible(), a11yScan()
```

## Philosophy

**Scan the real app, not mocks.** These tests run against a full Onyx deployment — the
same pages users see. axe-core evaluates the actual rendered DOM, catching issues that
static analysis and component-level tests miss (z-index stacking, dynamic content, focus
management, color contrast with real theme variables).

**Auto-discover pages.** Admin and settings tests scrape the sidebar/nav for links rather
than hardcoding routes. When someone adds a new admin page, it gets tested automatically.

**Start permissive, tighten progressively.** The ratchet approach means the initial merge
doesn't block anyone. Each rule fix is a small, focused PR. Once fixed, it never regresses.

**Fix by rule, not by page.** Group fixes by violation type (`button-name`, `link-name`,
`color-contrast`) rather than by page. Each rule type usually involves the same pattern
applied across many components — fixing the component fixes every page that uses it.

## CI integration

These tests run automatically as part of the `admin` Playwright project in
`pr-playwright-tests.yml`. No additional CI configuration is needed — they use the same
global setup, auth fixtures, retry/worker settings, and artifact uploads as all other
E2E tests.

Warning-mode violations appear in the Playwright HTML report as test annotations.
Strict-mode violations fail the test and block the PR.

## Running locally

```bash
# Run all accessibility tests
npx playwright test accessibility/

# Run a specific file
npx playwright test accessibility/public_pages.spec.ts

# Run with the HTML reporter for a browsable results page
npx playwright test accessibility/ --reporter=html
npx playwright show-report
```

## Writing new tests

### Simple: scan a page

```ts
import { test } from "@tests/e2e/fixtures/accessibility";

test("my page is accessible", async ({ page, expectAccessible }) => {
  await page.goto("/my-page");
  await page.waitForLoadState("networkidle");
  await expectAccessible();
});
```

### Scoping: include/exclude regions

```ts
await expectAccessible({
  include: ["main"],                // Only scan <main>
  exclude: ["#third-party-widget"], // Skip a known-bad embed
});
```

### Disabling specific rules

```ts
await expectAccessible({
  disableRules: ["label"], // Third-party datepicker, can't fix
});
```

### Using raw results

When you need programmatic access to violations (filtering, counting by impact):

```ts
import { test, expect } from "@tests/e2e/fixtures/accessibility";

test("no critical violations", async ({ page, a11yScan }) => {
  await page.goto("/my-page");
  await page.waitForLoadState("networkidle");

  const results = await a11yScan();
  const critical = results.violations.filter((v) => v.impact === "critical");
  expect(critical).toHaveLength(0);
});
```

### Adjusting WCAG level

```ts
// Stricter: WCAG 2.1 Level AAA
await expectAccessible({ level: "wcag-aaa" });

// Broadest: all axe rules including best-practice checks
await expectAccessible({ level: "all" });
```

## Current violations to fix

Prioritized by impact. Each row is a single focused PR.

| Priority | Rule | Impact | Scope | Fix |
|----------|------|--------|-------|-----|
| 1 | `button-name` | Critical | 7 icon-only buttons | Add `aria-label` to icon-only `<Button>` components |
| 2 | `aria-roles` | Critical | Chat input textarea | Fix invalid ARIA role on `#onyx-chat-input-textarea` |
| 3 | `link-name` | Serious | 57+ sidebar links | Add accessible text to sidebar agent/page links |
| 4 | `nested-interactive` | Serious | 53 sortable items | Restructure DnD sortable items to avoid nesting interactive elements |
| 5 | `color-contrast` | Serious | Sidebar section labels | Adjust `text-text-02` color token or use `text-text-03`+ |
| 6 | `aria-allowed-attr` | Critical | Radix collapsibles | Investigate `aria-controls` on Radix components (may need upstream fix or wrapper) |
| 7 | `scrollable-region-focusable` | Serious | Admin sidebar | Add `tabindex="0"` to scrollable sidebar container |
| 8 | `meta-viewport` | Moderate | Next.js viewport config | Remove `maximum-scale=1` / `user-scalable=no` from viewport meta |

## Common violations reference

| Rule | What it checks | Typical fix |
|------|---------------|-------------|
| `color-contrast` | Text has 4.5:1 contrast ratio | Use design system color tokens (text-03+ on neutral backgrounds) |
| `label` | Form inputs have accessible labels | Add `<label>`, `aria-label`, or `aria-labelledby` |
| `button-name` | Buttons have discernible text | Add text content or `aria-label` to icon-only buttons |
| `image-alt` | Images have alt text | Add `alt` attribute; decorative images get `alt=""` |
| `link-name` | Links have discernible text | Ensure link text is not empty |
| `region` | Content is within landmark regions | Wrap page sections in `<main>`, `<nav>`, `<aside>` |

Full rule reference: https://dequeuniversity.com/rules/axe/4.10
