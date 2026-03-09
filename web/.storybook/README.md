# Onyx Storybook

Storybook is an isolated development environment for UI components. It renders each component in a standalone "story" outside of the main app, so you can visually verify appearance, interact with props, and catch regressions without navigating through the full application.

The Onyx Storybook covers the full component library — from low-level `@opal/core` primitives up through `refresh-components` — giving designers and engineers a shared reference for every visual state.

**Production:** [onyx-storybook.vercel.app](https://onyx-storybook.vercel.app)

## Running Locally

```bash
cd web
npm run storybook        # dev server on http://localhost:6006
npm run storybook:build  # static build to storybook-static/
```

The dev server hot-reloads when you edit a component or story file.

## Writing Stories

Stories are **co-located** next to their component source:

```
lib/opal/src/core/interactive/
├── components.tsx              ← the component
├── Interactive.stories.tsx     ← the story
└── styles.css

src/refresh-components/buttons/
├── Button.tsx
└── Button.stories.tsx
```

### Minimal Template

```tsx
import type { Meta, StoryObj } from "@storybook/react";
import { MyComponent } from "./MyComponent";

const meta: Meta<typeof MyComponent> = {
  title: "Category/MyComponent",   // sidebar path
  component: MyComponent,
  tags: ["autodocs"],               // generates a docs page from props
};

export default meta;
type Story = StoryObj<typeof MyComponent>;

export const Default: Story = {
  args: { label: "Hello" },
};
```

### Conventions

- **Title format:** `Core/Name`, `Components/Name`, `Layouts/Name`, or `refresh-components/category/Name`
- **Tags:** Add `tags: ["autodocs"]` to auto-generate a props docs page
- **Decorators:** Components that use Radix tooltips need a `TooltipPrimitive.Provider` decorator
- **Layout:** Use `parameters: { layout: "fullscreen" }` for modals/popovers that use portals

## Dark Mode

Use the theme toggle (paint roller icon) in the Storybook toolbar to switch between light and dark modes. This adds/removes the `dark` class on the preview body, matching the app's `darkMode: "class"` Tailwind config. All color tokens from `colors.css` adapt automatically.

## Deployment

The production Storybook is deployed as a static site on Vercel. The build runs `npm run storybook:build` which outputs to `storybook-static/`, and Vercel serves that directory.

Deploys are triggered on merges to `main` when files in `web/lib/opal/`, `web/src/refresh-components/`, or `web/.storybook/` change.

## Component Layers

The sidebar organizes components by their layer in the design system:

| Layer | Path | Examples |
|-------|------|----------|
| **Core** | `lib/opal/src/core/` | Interactive, Hoverable |
| **Components** | `lib/opal/src/components/` | Button, OpenButton, Tag |
| **Layouts** | `lib/opal/src/layouts/` | Content, ContentAction, IllustrationContent |
| **refresh-components** | `src/refresh-components/` | Inputs, tables, modals, text, cards, tiles, etc. |
