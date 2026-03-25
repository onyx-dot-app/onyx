# Frontend Standards

This file is the single source of truth for frontend coding standards across all Onyx frontend
projects (including, but not limited to, `/web`, `/desktop`).

# Components

UI components are spread across several directories while the codebase migrates to Opal:

- **`web/lib/opal/src/`** — The Opal design system. Preferred for all new components.
- **`web/src/refresh-components/`** — Production components not yet migrated to Opal.
- **`web/src/sections/`** — Feature-specific composite components (cards, modals, etc.).
- **`web/src/layouts/`** — Page-level layout components (settings pages, etc.).

**Do NOT use anything from `web/src/components/`** — this directory contains legacy components
that are being phased out. Always prefer Opal first; fall back to `refresh-components` only for
components not yet available in Opal.

## Opal Layouts (`lib/opal/src/layouts/`)

All layout primitives are imported from `@opal/layouts`. They handle sizing, font selection, icon
alignment, and optional inline editing.

```typescript
import { Content, ContentAction, IllustrationContent } from "@opal/layouts";
```

### Content

**Use this for any combination of icon + title + description.**

A two-axis layout component that automatically routes to the correct internal layout
(`ContentXl`, `ContentLg`, `ContentMd`, `ContentSm`) based on `sizePreset` and `variant`:

| sizePreset | variant | Routes to | Layout |
|---|---|---|---|
| `headline` / `section` | `heading` | `ContentXl` | Icon on top (flex-col) |
| `headline` / `section` | `section` | `ContentLg` | Icon inline (flex-row) |
| `main-content` / `main-ui` / `secondary` | `section` / `heading` | `ContentMd` | Compact inline |
| `main-content` / `main-ui` / `secondary` | `body` | `ContentSm` | Body text layout |

```typescript
<Content
  sizePreset="main-ui"
  variant="section"
  icon={SvgSettings}
  title="Settings"
  description="Manage your preferences"
/>
```

### ContentAction

**Use this when a Content block needs right-side actions** (buttons, badges, icons, etc.).

Wraps `Content` and adds a `rightChildren` slot. Accepts all `Content` props plus:
- `rightChildren`: `ReactNode` — actions rendered on the right
- `paddingVariant`: `SizeVariant` — controls outer padding

```typescript
<ContentAction
  sizePreset="main-ui"
  variant="section"
  icon={SvgUser}
  title="John Doe"
  description="Admin"
  rightChildren={<Button icon={SvgEdit}>Edit</Button>}
/>
```

### IllustrationContent

**Use this for empty states, error pages, and informational placeholders.**

A vertically-stacked, center-aligned layout that pairs a large illustration (7.5rem x 7.5rem)
with a title and optional description.

```typescript
import SvgNoResult from "@opal/illustrations/no-result";

<IllustrationContent
  illustration={SvgNoResult}
  title="No results found"
  description="Try adjusting your search or filters."
/>
```

Props:
- `illustration`: `IconFunctionComponent` — optional, from `@opal/illustrations`
- `title`: `string` — required
- `description`: `string` — optional

## Settings Page Layout (`src/layouts/settings-layouts.tsx`)

**Use this for all admin/settings pages.** Provides a standardized layout with scroll-aware
sticky headers, centered content containers, and responsive behavior.

```typescript
import SettingsLayouts from "@/layouts/settings-layouts";

function MySettingsPage() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgSettings}
        title="Account Settings"
        description="Manage your account preferences"
        rightChildren={<Button>Save</Button>}
      >
        <InputTypeIn placeholder="Search settings..." />
      </SettingsLayouts.Header>

      <SettingsLayouts.Body>
        <Card>Settings content here</Card>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
```

Sub-components:
- **`SettingsLayouts.Root`** — Wrapper with centered, scrollable container. Width options:
  `"sm"` (672px), `"sm-md"` (752px), `"md"` (872px, default), `"lg"` (992px), `"full"` (100%).
- **`SettingsLayouts.Header`** — Sticky header with icon, title, description, optional
  `rightChildren` actions, optional `children` below (e.g., search/filter), optional `backButton`,
  and optional `separator`. Automatically shows a scroll shadow when scrolled.
- **`SettingsLayouts.Body`** — Content container with consistent padding and vertical spacing.

## Cards (`src/sections/cards/`)

**When building a card that displays information about a specific entity (agent, document set,
file, connector, etc.), add it to `web/src/sections/cards/`.**

Each card is a self-contained component focused on a single entity type. Cards typically include
entity identification (name, avatar, icon), summary information, and quick actions.

```typescript
import AgentCard from "@/sections/cards/AgentCard";
import DocumentSetCard from "@/sections/cards/DocumentSetCard";
import FileCard from "@/sections/cards/FileCard";
```

Guidelines:
- One card per entity type — keep card-specific logic within the card component.
- Cards should be reusable across different pages and contexts.
- Use shared components from `@opal/components`, `@opal/layouts`, and `@/refresh-components`
  inside cards — do not duplicate layout or styling logic.

## Button (`components/buttons/button/`)

**Always use the Opal `Button`.** Do not use raw `<button>` elements.

Built on `Interactive.Stateless` > `Interactive.Container`, so it inherits the full color/state
system automatically.

```typescript
import { Button } from "@opal/components/buttons/button/components";

// Labeled button
<Button variant="default" prominence="primary" icon={SvgPlus}>
  Create
</Button>

// Icon-only button (omit children)
<Button variant="default" prominence="tertiary" icon={SvgTrash} size="sm" />
```

Key props:
- `variant`: `"default"` | `"action"` | `"danger"` | `"none"`
- `prominence`: `"primary"` | `"secondary"` | `"tertiary"` | `"internal"`
- `size`: `"lg"` | `"md"` | `"sm"` | `"xs"` | `"2xs"` | `"fit"`
- `icon`, `rightIcon`, `children`, `disabled`, `href`, `tooltip`

## Core Primitives (`core/`)

The `core/` directory contains the lowest-level building blocks that power all Opal components.
**Most code should not interface with these directly** — use higher-level components like `Button`,
`Content`, and `ContentAction` instead. These are documented here for understanding, not everyday use.

### Interactive (`core/interactive/`)

The foundational layer for all clickable/interactive surfaces. Defines the color matrix for
hover, active, and disabled states.

- **`Interactive.Stateless`** — Color system for stateless elements (buttons, links). Applies
  variant/prominence/state combinations via CSS custom properties.
- **`Interactive.Stateful`** — Color system for stateful elements (toggles, sidebar items, selects).
  Uses `state` (`"empty"` | `"filled"` | `"selected"`) instead of prominence.
- **`Interactive.Container`** — Structural box providing height, rounding, padding, and border.
  Shared by both Stateless and Stateful. Renders as `<div>`, `<button>`, or `<Link>` depending
  on context.
- **`Interactive.Foldable`** — Zero-width collapsible wrapper with CSS grid animation.

### Disabled (`core/disabled/`)

Propagates disabled state via React context. `Interactive.Stateless` and `Interactive.Stateful`
consume this automatically, so wrapping a subtree in `<Disabled disabled={true}>` disables all
interactive descendants.

### Hoverable (`core/animations/`)

A standardized way to provide "opacity-100 on hover" behavior. Instead of manually wiring
`opacity-0 group-hover:opacity-100` with Tailwind, use `Hoverable` for consistent, coordinated
hover-to-reveal patterns.

- **`Hoverable.Root`** — Wraps a hover group. Tracks mouse enter/leave and broadcasts hover
  state to descendants via a per-group React context.
- **`Hoverable.Item`** — Marks an element that should appear on hover. Supports two modes:
  - **Group mode** (`group` prop provided): visibility driven by a matching `Hoverable.Root`
    ancestor. Throws if no matching Root is found.
  - **Local mode** (`group` omitted): uses CSS `:hover` on the item itself.

```typescript
import { Hoverable } from "@opal/core";

// Group mode — hovering anywhere on the row reveals the trash icon
<Hoverable.Root group="row">
  <div className="flex items-center gap-2">
    <span>Row content</span>
    <Hoverable.Item group="row" variant="opacity-on-hover">
      <SvgTrash />
    </Hoverable.Item>
  </div>
</Hoverable.Root>

// Local mode — hovering the item itself reveals it
<Hoverable.Item variant="opacity-on-hover">
  <SvgTrash />
</Hoverable.Item>
```

# Best Practices

## 1. Tailwind Dark Mode

**Strictly forbid using the `dark:` modifier in Tailwind classes, except for logo icon handling.**

**Reason:** The `colors.css` file already, VERY CAREFULLY, defines what the exact opposite colour of each light-mode colour is. Overriding this behaviour is VERY bad and will lead to horrible UI breakages.

**Exception:** The `createLogoIcon` helper in `web/src/components/icons/icons.tsx` uses `dark:` modifiers (`dark:invert`, `dark:hidden`, `dark:block`) to handle third-party logo icons that cannot automatically adapt through `colors.css`. This is the ONLY acceptable use of dark mode modifiers.

```typescript
// ✅ Good - Standard components use `tailwind-themes/tailwind.config.js` / `src/app/css/colors.css`
<div className="bg-background-neutral-03 text-text-02">
  Content
</div>

// ✅ Good - Logo icons with dark mode handling via createLogoIcon
export const GithubIcon = createLogoIcon(githubLightIcon, {
  monochromatic: true,  // Will apply dark:invert internally
});

export const GitbookIcon = createLogoIcon(gitbookLightIcon, {
  darkSrc: gitbookDarkIcon,  // Will use dark:hidden/dark:block internally
});

// ❌ Bad - Manual dark mode overrides
<div className="bg-white dark:bg-black text-black dark:text-white">
  Content
</div>
```

## 2. Icon Usage

**ONLY use icons from the `web/src/icons` directory. Do NOT use icons from `react-icons`, `lucide`, or other external libraries.**

**Reason:** We have a very carefully curated selection of icons that match our Onyx guidelines. We do NOT want to muddy those up with different aesthetic stylings.

```typescript
// ✅ Good
import SvgX from "@/icons/x";
import SvgMoreHorizontal from "@/icons/more-horizontal";

// ❌ Bad
import { User } from "lucide-react";
import { FiSearch } from "react-icons/fi";
```

**Missing Icons**: If an icon is needed but doesn't exist in the `web/src/icons` directory, import it from Figma using the Figma MCP tool and add it to the icons directory.
If you need help with this step, reach out to `raunak@onyx.app`.

## 3. Text Rendering

**Use the Opal `Text` component for all text rendering. Avoid "naked" text nodes.**

**Reason:** The `Text` component is fully compliant with the stylings provided in Figma. It uses
string-enum props (`font` and `color`) for font preset and color selection, and supports inline
markdown rendering by default.

```typescript
// ✅ Good — Opal Text with string-enum props
import { Text } from "@opal/components";

function UserCard({ name }: { name: string }) {
  return (
    <Text font="main-ui-action" color="text-03">
      {name}
    </Text>
  )
}

// ✅ Good — inline markdown (enabled by default for string children)
<Text font="main-ui-body" color="text-05">
  {"*Hello*, **world**! Visit [Onyx](https://onyx.app) and run `onyx start`."}
</Text>

// ✅ Good — opt out of markdown when rendering user-generated content
<Text font="main-ui-body" color="text-03" preventMarkdown>
  {userProvidedString}
</Text>

// ❌ Bad — legacy boolean-flag API (still works but deprecated)
import Text from "@/refresh-components/texts/Text";
<Text text03 mainUiAction>{name}</Text>

// ❌ Bad — naked text nodes
<div>
  <h2>{name}</h2>
  <p>User details</p>
</div>
```

Key props:
- `font`: `TextFont` — font preset (e.g., `"main-ui-body"`, `"heading-h2"`, `"secondary-action"`)
- `color`: `TextColor` — text color (e.g., `"text-03"`, `"text-05"`)
- `inverted`: `boolean` — use inverted color palette for dark backgrounds
- `as`: `"p" | "span" | "li"` — HTML tag (default: `"span"`)
- `preventMarkdown`: `boolean` — disable inline markdown parsing

## 4. Component Usage

**Heavily avoid raw HTML input components. Always use components from the `web/src/refresh-components` or `web/lib/opal/src` directory.**

**Reason:** We've put in a lot of effort to unify the components that are rendered in the Onyx app. Using raw components breaks the entire UI of the application, and leaves it in a muddier state than before.

```typescript
// ✅ Good
import Button from '@/refresh-components/buttons/Button'
import InputTypeIn from '@/refresh-components/inputs/InputTypeIn'
import SvgPlusCircle from '@/icons/plus-circle'

function ContactForm() {
  return (
    <form>
      <InputTypeIn placeholder="Search..." />
      <Button type="submit" leftIcon={SvgPlusCircle}>Submit</Button>
    </form>
  )
}

// ❌ Bad
function ContactForm() {
  return (
    <form>
      <input placeholder="Name" />
      <textarea placeholder="Message" />
      <button type="submit">Submit</button>
    </form>
  )
}
```

## 5. Colors

**Always use custom overrides for colors and borders rather than built in Tailwind CSS colors. These overrides live in `web/tailwind-themes/tailwind.config.js`.**

**Reason:** Our custom color system uses CSS variables that automatically handle dark mode and maintain design consistency across the app. Standard Tailwind colors bypass this system.

**Available color categories:**

- **Text:** `text-01` through `text-05`, `text-inverted-XX`
- **Backgrounds:** `background-neutral-XX`, `background-tint-XX` (and inverted variants)
- **Borders:** `border-01` through `border-05`, `border-inverted-XX`
- **Actions:** `action-link-XX`, `action-danger-XX`
- **Status:** `status-info-XX`, `status-success-XX`, `status-warning-XX`, `status-error-XX`
- **Theme:** `theme-primary-XX`, `theme-red-XX`, `theme-blue-XX`, etc.

```typescript
// ✅ Good - Use custom Onyx color classes
<div className="bg-background-neutral-01 border border-border-02" />
<div className="bg-background-tint-02 border border-border-01" />
<div className="bg-status-success-01" />
<div className="bg-action-link-01" />
<div className="bg-theme-primary-05" />

// ❌ Bad - Do NOT use standard Tailwind colors
<div className="bg-gray-100 border border-gray-300 text-gray-600" />
<div className="bg-white border border-slate-200" />
<div className="bg-green-100 text-green-700" />
<div className="bg-blue-100 text-blue-600" />
<div className="bg-indigo-500" />
```

## 6. Data Fetching

**Prefer using `useSWR` for data fetching. Data should generally be fetched on the client side. Components that need data should display a loader / placeholder while waiting for that data. Prefer loading data within the component that needs it rather than at the top level and passing it down.**

**Reason:** Client side fetching allows us to load the skeleton of the page without waiting for data to load, leading to a snappier UX. Loading data where needed reduces dependencies between a component and its parent component(s).

# Stylistic Preferences

## 1. Import Standards

**Always use absolute imports with the `@` prefix.**

**Reason:** Moving files around becomes easier since you don't also have to update those import statements. This makes modifications to the codebase much nicer.

```typescript
// ✅ Good
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { Text } from "@/refresh-components/texts/Text";

// ❌ Bad
import { Button } from "../../../components/ui/button";
import { useAuth } from "./hooks/useAuth";
```

## 2. React Component Functions

**Prefer regular functions over arrow functions for React components.**

**Reason:** Functions just become easier to read.

```typescript
// ✅ Good
function UserProfile({ userId }: UserProfileProps) {
  return <div>User Profile</div>
}

// ❌ Bad
const UserProfile = ({ userId }: UserProfileProps) => {
  return <div>User Profile</div>
}
```

## 3. Props Interface Extraction

**Extract prop types into their own interface definitions. Keep prop interfaces in the same file
as the component they belong to. Non-prop types (shared models, API response shapes, enums, etc.)
should be placed in a co-located `interfaces.ts` file.**

**Reason:** Prop interfaces are tightly coupled to their component and rarely imported elsewhere,
so co-location keeps things simple. Shared types belong in `interfaces.ts` so they can be
imported without pulling in component code.

```typescript
// ✅ Good — props interface in the same file as the component
// UserCard.tsx
interface UserCardProps {
  user: User
  showActions?: boolean
  onEdit?: (userId: string) => void
}

function UserCard({ user, showActions = false, onEdit }: UserCardProps) {
  return <div>User Card</div>
}

// ✅ Good — shared types in interfaces.ts
// interfaces.ts
export interface User {
  id: string
  name: string
  role: UserRole
}

export type UserRole = "admin" | "member" | "viewer"

// ❌ Bad — inline prop types
function UserCard({
  user,
  showActions = false,
  onEdit
}: {
  user: User
  showActions?: boolean
  onEdit?: (userId: string) => void
}) {
  return <div>User Card</div>
}
```

## 4. Spacing Guidelines

**Prefer padding over margins for spacing. When a library component exposes a padding prop
(e.g., `paddingVariant`), use that prop instead of wrapping it in a `<div>` with padding classes.
If a library component does not expose a padding override and you find yourself adding a wrapper
div for spacing, consider updating the library component to accept one.**

**Reason:** We want to consolidate usage to paddings instead of margins, and minimize wrapper
divs that exist solely for spacing.

```typescript
// ✅ Good — use the component's padding prop
<ContentAction paddingVariant="md" ... />

// ✅ Good — padding utilities when no component prop exists
<div className="p-4 space-y-2">
  <div className="p-2">Content</div>
</div>

// ❌ Bad — wrapper div just for spacing
<div className="p-4">
  <ContentAction ... />
</div>

// ❌ Bad — margins
<div className="m-4 space-y-2">
  <div className="m-2">Content</div>
</div>
```

## 5. Class Name Utilities

**Use the `cn` utility instead of raw string formatting for classNames.**

**Reason:** `cn`s are easier to read. They also allow for more complex types (i.e., string-arrays) to get formatted properly (it flattens each element in that string array down). As a result, it can allow things such as conditionals (i.e., `myCondition && "some-tailwind-class"`, which evaluates to `false` when `myCondition` is `false`) to get filtered out.

```typescript
import { cn } from '@/lib/utils'

// ✅ Good
<div className={cn(
  'base-class',
  isActive && 'active-class',
  className
)}>
  Content
</div>

// ❌ Bad
<div className={`base-class ${isActive ? 'active-class' : ''} ${className}`}>
  Content
</div>
```

## 6. Custom Hooks Organization

**Follow a "hook-per-file" layout. Each hook should live in its own file within `web/src/hooks`.**

**Reason:** This is just a layout preference. Keeps code clean.

```typescript
// web/src/hooks/useUserData.ts
export function useUserData(userId: string) {
  // hook implementation
}

// web/src/hooks/useLocalStorage.ts
export function useLocalStorage<T>(key: string, initialValue: T) {
  // hook implementation
}
```
