# Web Standards

This document outlines the coding standards and best practices for the `web` directory Next.js project.

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

**Extract prop types into their own interface definitions.**

**Reason:** Functions just become easier to read.

```typescript
// ✅ Good
interface UserCardProps {
  user: User
  showActions?: boolean
  onEdit?: (userId: string) => void
}

function UserCard({ user, showActions = false, onEdit }: UserCardProps) {
  return <div>User Card</div>
}

// ❌ Bad
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

**Prefer padding over margins for spacing.**

**Reason:** We want to consolidate usage to paddings instead of margins.

```typescript
// ✅ Good
<div className="p-4 space-y-2">
  <div className="p-2">Content</div>
</div>

// ❌ Bad
<div className="m-4 space-y-2">
  <div className="m-2">Content</div>
</div>
```

## 5. Tailwind Dark Mode

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

## 6. Class Name Utilities

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

## 7. Custom Hooks Organization

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

## 8. Icon Usage

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

## 9. Text Rendering

**Prefer using the `refresh-components/texts/Text` component for all text rendering. Avoid "naked" text nodes.**

**Reason:** The `Text` component is fully compliant with the stylings provided in Figma. It provides easy utilities to specify the text-colour and font-size in the form of flags. Super duper easy.

```typescript
// ✅ Good
import { Text } from '@/refresh-components/texts/Text'

function UserCard({ name }: { name: string }) {
  return (
    <Text
      {/* The `text03` flag makes the text it renders to be coloured the 3rd-scale grey */}
      text03
      {/* The `mainAction` flag makes the text it renders to be "main-action" font + line-height + weightage, as described in the Figma */}
      mainAction
    >
      {name}
    </Text>
  )
}

// ❌ Bad
function UserCard({ name }: { name: string }) {
  return (
    <div>
      <h2>{name}</h2>
      <p>User details</p>
    </div>
  )
}
```

## 10. Component Usage

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

## 11. Colors

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

## 12. Data Fetching

**Prefer using `useSWR` for data fetching. Data should generally be fetched on the client side. Components that need data should display a loader / placeholder while waiting for that data. Prefer loading data within the component that needs it rather than at the top level and passing it down.**

**Reason:** Client side fetching allows us to load the skeleton of the page without waiting for data to load, leading to a snappier UX. Loading data where needed reduces dependencies between a component and its parent component(s).
