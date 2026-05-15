# Playwright E2E Test Rules

Hard rules for tests under `web/tests/e2e/`. Read before adding or modifying a spec.

For the broader Onyx testing strategy and where Playwright fits among unit / external-dependency / integration tests, see `CLAUDE.md` ("Testing Strategy") and `backend/tests/README.md`. For Jest + React Testing Library guidance for component tests, see `web/tests/README.md`.

## 1. Use the Page Object Model

All locators and interactions for a UI surface live on a Page Object class — never inline in a spec.

- One class per surface (e.g. `ChatPage`, `InputBar`, `AdminUsersPage`).
- Composite pages expose nested objects: `chatPage.inputBar.someMethod()`.
- Specs call methods on the page object. They do not construct locators.
- When extending coverage for an area that has no page object, create one before writing the spec.

```typescript
// ✅ Good — spec calls into the POM
await chatPage.goto();
await chatPage.inputBar.type("hello");
await chatPage.inputBar.send();
await chatPage.expectHumanMessage("hello");

// ❌ Bad — raw locators in the spec
await page.goto("/app");
await page.locator('[contenteditable="true"]').fill("hello");
await page.keyboard.press("Enter");
await expect(page.locator(".message")).toContainText("hello");
```

**Why:** specs that read like a description of user behavior are easier to scan, review, and refactor. Locator churn changes one POM method, not every spec that touched the surface.

## 2. Use auto-retrying matchers — never `getAttribute` / `evaluate` for async state

Playwright's `expect(locator).*` matchers retry until the assertion passes or the timeout expires. `locator.getAttribute()` and `page.evaluate()` are single snapshots — they read the DOM exactly once and fail immediately on a stale read.

If the value can be set by a React state update, an effect, a microtask, or anything else asynchronous, snapshot reads will flake.

| Asserting on | Use                                                              | Don't use                                         |
| ------------ | ---------------------------------------------------------------- | ------------------------------------------------- |
| Attribute    | `expect(locator).toHaveAttribute(name, value)`                   | `locator.getAttribute(name)` then `expect(...)`   |
| Class        | `expect(locator).toHaveClass(/regex/)` / `.not.toHaveClass(...)` | `page.evaluate(el => el.classList.contains(...))` |
| Text         | `expect(locator).toHaveText(value)` / `toContainText(value)`     | `locator.textContent()` then `expect(...)`        |
| Count        | `expect(locator).toHaveCount(n)`                                 | `locator.count()` then `expect(...)`              |
| Visibility   | `expect(locator).toBeVisible()` / `toBeHidden()`                 | manual `isVisible()` checks                       |
| Value        | `expect(locator).toHaveValue(value)`                             | `locator.inputValue()` then `expect(...)`         |

```typescript
// ✅ Good — retries until the attribute settles
await expect(tile).toHaveAttribute("data-text", "modified text");

// ❌ Bad — one-shot read, flakes when the attribute updates after a React render
const text = await tile.getAttribute("data-text");
expect(text).toBe("modified text");

// ✅ Good — retries until the class settles
await expect(tile.first()).toHaveClass(/rich-input-tile-selected/);

// ❌ Bad — one-shot DOM snapshot
const selected = await page.evaluate(
  () => !!document.querySelector(".rich-input-tile-selected")
);
expect(selected).toBe(true);
```

`getAttribute` / `evaluate` / `textContent` / `count` are still appropriate when you need the value for control flow inside the spec (e.g. branching on it, logging it). They are not appropriate as the basis of an assertion on async state.
