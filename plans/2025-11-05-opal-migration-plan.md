# Opal Migration Execution Plan

**Date:** 2025-11-05  
**Goal:** Port universal components, icons, logos, and hooks from `web/src` to `web/libs/opal`

---

## Directory Structure in Opal

**Export Strategy:** Option 3 - Single `src/index.ts` only  
**Rationale:** Prevents import path confusion. Only ONE canonical import path: `import { X } from "@onyx/opal"`

```
web/lib/opal/                       # Note: 'lib' not 'libs'
├── src/
│   ├── index.ts                    # ONLY export file (explicit named exports)
│   ├── components/                 # UI Components
│   │   ├── buttons/
│   │   │   ├── Button.tsx
│   │   │   ├── IconButton.tsx
│   │   │   └── ...
│   │   ├── text/
│   │   │   ├── Text.tsx
│   │   │   └── Truncated.tsx
│   │   ├── inputs/
│   │   ├── modals/
│   │   ├── loaders/
│   │   └── ...
│   ├── icons/                      # SVG Icons
│   │   ├── types.ts                # SvgProps, IconProps
│   │   ├── check.tsx
│   │   ├── arrow-right.tsx
│   │   └── ... (110+ icons)
│   ├── logos/                      # Brand Logos
│   │   ├── OnyxLogo.tsx
│   │   └── ...
│   ├── hooks/                      # React Hooks
│   │   ├── useBoundingBox.ts
│   │   ├── useClickOutside.ts
│   │   ├── useKeyPress.ts
│   │   └── ...
│   └── utils/                      # Utilities
│       └── cn.ts                   # Tailwind merge utility
├── package.json
├── tsconfig.json
└── README.md
```

**Note:** No intermediate `index.ts` files in subdirectories. All exports managed in single `src/index.ts`.

---

## Phase 1: Foundation Setup ✅ HIGHEST PRIORITY

### 1.1 Create Directory Structure

```bash
cd web/libs/opal/src
mkdir -p components icons logos hooks utils
```

### 1.2 Add Core Utilities

**File: `src/utils/cn.ts`**
```typescript
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

**Note:** No `src/utils/index.ts` needed (using Option 3 - single export file)

### 1.3 Update Opal Dependencies

**Add to `package.json`:**
```json
{
  "dependencies": {
    "clsx": "^2.1.1",
    "tailwind-merge": "^2.5.4"
  }
}
```

### 1.4 Update Web's Tailwind Config

**File: `web/tailwind.config.js`**

Ensure content includes opal:
```js
content: [
  "./src/**/*.{ts,tsx}",
  "./lib/opal/src/**/*.{ts,tsx}", // Note: 'lib' not 'libs'
]
```

---

## Phase 2: Icons Migration (110+ files) ✅ PRIORITY

### 2.1 Copy Icon Type Definitions

**File: `src/icons/types.ts`**
```typescript
export interface SvgProps {
  className?: string;
}

export interface IconProps extends React.SVGProps<SVGSVGElement> {
  size?: number | string;
  title?: string;
  color?: string;
}
```

### 2.2 Migrate All Icon Files

**Command:**
```bash
# Copy all icon files from web/src/icons to opal/src/icons
cp web/src/icons/*.tsx web/libs/opal/src/icons/

# Except index.tsx (we'll create our own)
rm web/libs/opal/src/icons/index.tsx 2>/dev/null
```

**Icons to migrate (all 110+ files):**
- ✅ actions.tsx
- ✅ activity.tsx
- ✅ add-lines.tsx
- ✅ alert-circle.tsx
- ✅ alert-triangle.tsx
- ✅ arrow-*.tsx (all arrow variants)
- ✅ check.tsx
- ✅ check-circle.tsx
- ✅ ... (all remaining icons)

### 2.3 Add Icon Exports to Main Index

**File: `src/index.ts`**

Add explicit icon exports to the main index file:
```typescript
// Icons (explicit exports, no intermediate index.ts)
export { default as Actions } from './icons/actions';
export { default as Activity } from './icons/activity';
export { default as AddLines } from './icons/add-lines';
export { default as AlertCircle } from './icons/alert-circle';
export { default as AlertTriangle } from './icons/alert-triangle';
// ... etc for all 110+ icons
export * from './icons/types';
```

**Note:** Can use script to generate these exports, but they go directly in `src/index.ts`, not in `src/icons/index.ts`

### 2.4 Update Icon Imports in Web

**Before:**
```typescript
import CheckIcon from "@/icons/check";
```

**After:**
```typescript
import { Check as CheckIcon } from "@onyx/opal";
```

---

## Phase 3: Hooks Migration ✅ PRIORITY

### 3.1 Universal Hooks to Migrate

These hooks have NO business logic dependencies:

#### ✅ `useBoundingBox.ts`
- **Purpose:** Track if mouse is inside element bounds
- **Dependencies:** None
- **Action:** Copy as-is

#### ✅ `useClickOutside.ts`
- **Purpose:** Detect clicks outside an element
- **Dependencies:** None
- **Action:** Copy as-is (already well-documented)

#### ✅ `useKeyPress.ts`
- **Purpose:** Keyboard event handling (Escape, Enter)
- **Dependencies:** None
- **Action:** Copy as-is
- **Note:** Has "use client" directive

### 3.2 Hooks to SKIP (Web-Specific)

#### ❌ `appNavigation.ts`
- **Reason:** Next.js router dependency
- **Keep in:** web/src/hooks

#### ❌ `usePaginatedFetch.tsx`
- **Reason:** API fetching logic, server-specific
- **Keep in:** web/src/hooks

#### ❌ `useTokenRefresh.ts`
- **Reason:** Authentication logic
- **Keep in:** web/src/hooks

#### ❌ `input-prompts.ts`
- **Reason:** App-specific prompt logic
- **Keep in:** web/src/hooks

#### ❌ `useScreenSize.ts`
- **Reason:** Consider migrating, but low priority

### 3.3 Migration Steps

```bash
# Copy universal hooks
cp web/src/hooks/useBoundingBox.ts web/lib/opal/src/hooks/
cp web/src/hooks/useClickOutside.ts web/lib/opal/src/hooks/
cp web/src/hooks/useKeyPress.ts web/lib/opal/src/hooks/
```

**Add to `src/index.ts`:**
```typescript
// Hooks (explicit exports, no intermediate index.ts)
export { useBoundingBox } from "./hooks/useBoundingBox";
export { useClickOutside } from "./hooks/useClickOutside";
export { useKeyPress, useEscape, useEnter } from "./hooks/useKeyPress";
```

### 3.4 Update Hook Imports in Web

**Before:**
```typescript
import { useClickOutside } from "@/hooks/useClickOutside";
import { useEscape } from "@/hooks/useKeyPress";
```

**After:**
```typescript
import { useClickOutside, useEscape } from "@onyx/opal";
```

---

## Phase 4: Logos Migration

### 4.1 Identify Logo Files

Current logo locations:
- `web/src/icons/onyx-logo.tsx`
- `web/src/components/logo/Logo.tsx`
- `web/src/refresh-components/Logo.tsx`

### 4.2 Decision: Logo Handling

**Option A:** Migrate generic logo component structure
- Create `<Logo>` component that accepts logo source
- App provides actual logo files

**Option B:** Don't migrate logos (brand-specific)
- Keep in web (RECOMMENDED)
- Logos are brand/app specific

**RECOMMENDATION:** ❌ Do NOT migrate logos to opal
- Logos are brand-specific (Onyx branding)
- Not reusable across different apps
- Keep in `web/src`

---

## Phase 5: Component Migration

### 5.1 Priority 1 Components (No Dependencies)

#### ✅ Text Components - ALL 2 TEXT HELPERS ARE UNIVERSAL

**Analysis:** Both text components in `refresh-components/texts/` are pure presentational helpers with zero app-specific logic.

**Files to Migrate:**
1. ✅ `texts/Text.tsx` - Already migrated - Typography component with font/color variants
2. ✅ `texts/Truncated.tsx` - Text truncation with tooltip support

**Dependencies (All Universal):**
- `cn` utility from `@/utils` ✅
- Tailwind classes ✅
- React hooks (useState, useRef, useEffect in Truncated)
- Shadcn UI Tooltip (in Truncated - universal)

**Migration Status:**
- Text.tsx: ✅ Already migrated to `opal/src/components/texts/Text.tsx`
- Truncated.tsx: ⏳ Needs migration

**Migration Strategy for Truncated.tsx:**
1. Copy file to `opal/src/components/texts/Truncated.tsx`
2. Update imports to use `@/` alias
3. Change `@/lib/utils` → `@/utils`
4. Change `@/components/ui/tooltip` → keep as-is (Shadcn UI is universal)
5. Ensure it uses default export
6. Add export to main `src/index.ts`

**Current Directory Structure:**
```
opal/src/components/texts/
├── Text.tsx          ✅ Migrated
└── Truncated.tsx     ⏳ To migrate
```

#### ✅ Simple Utilities

**Files:**
- `refresh-components/OverflowDiv.tsx`
- `refresh-components/SimpleTooltip.tsx`
- `refresh-components/CounterSeparator.tsx`

**Action:** Migrate to `components/utilities/`

#### ✅ Loaders

**Files:**
- `refresh-components/loaders/SimpleLoader.tsx`

**Action:** Migrate to `components/loaders/`

### 5.2 Priority 2 Components (Icon Dependencies)

#### ✅ Button Components - ALL 11 BUTTONS ARE UNIVERSAL

**Analysis:** All button components in `refresh-components/buttons/` are pure presentational components with zero app-specific logic. They should ALL be migrated.

**Files to Migrate:**
1. ✅ `buttons/Button.tsx` - Already migrated
2. ✅ `buttons/IconButton.tsx` - Icon button with tooltip support
3. ✅ `buttons/CopyIconButton.tsx` - Clipboard functionality (uses browser API only)
4. ✅ `buttons/CreateButton.tsx` - Simple wrapper with default icon
5. ✅ `buttons/AttachmentButton.tsx` - File attachment display (pure UI)
6. ✅ `buttons/FilterButton.tsx` - Generic filter button UI
7. ✅ `buttons/SelectButton.tsx` - Dropdown select with animation
8. ✅ `buttons/MenuButton.tsx` - Navigation menu item
9. ✅ `buttons/LineItem.tsx` - List item button ⚠️ **Has debug `bg-red` class to remove**
10. ✅ `buttons/SidebarTab.tsx` - Sidebar navigation tab
11. ✅ `buttons/Tag.tsx` - Generic tag component

**Common Dependencies (All Universal):**
- `Text` and `Truncated` components (from Phase 5.1)
- `cn` utility from `@/utils`
- `SvgProps` type from icons
- `next/link` (framework standard - keep as-is)
- Shadcn UI components (tooltip, checkbox - universal)
- React hooks (useState, useEffect, useRef, useMemo)
- Browser APIs (Clipboard API in CopyIconButton)

**Migration Strategy:**
1. Copy all button files to `opal/src/components/buttons/`
2. Update all imports to use `@/` alias (absolute paths within opal)
3. Change `@/lib/utils` → `@/utils`
4. Change `@/refresh-components/texts/Text` → `@/components/texts/Text`
5. Change `@/refresh-components/texts/Truncated` → `@/components/texts/Truncated`
6. Fix LineItem.tsx debug code: remove or fix `bg-red` class
7. Ensure all components use default export
8. Add all exports to main `src/index.ts`

**No Business Logic Issues:**
- ✅ Zero API calls
- ✅ Zero app-specific state
- ✅ Zero domain knowledge
- ✅ All content passed via props
- ✅ Pure presentational components

### 5.3 Components to SKIP (Business Logic)

#### ❌ Context Providers
- `contexts/ChatContext.tsx`
- `contexts/ChatModalContext.tsx`
- `contexts/AgentsContext.tsx`
- `contexts/AppSidebarContext.tsx`

**Reason:** Business logic, state management, API calls

#### ❌ Domain-Specific Components
- `AgentCard.tsx` - Agent-specific
- `AgentIcon.tsx` - Agent-specific
- `Attachment.tsx` - File handling
- `Logo.tsx` - Branding

#### ❌ Complex Features
- `onboarding/` - App-specific flow
- `page-components/` - App layout
- `popovers/FilePickerPopover.tsx` - File system
- `popovers/LLMPopover.tsx` - LLM logic
- `popovers/ActionsPopover/` - Action system

#### ❌ Form Components with Formik
- `form/FormikField.tsx`
- Consider migrating generic form components later

---

## Phase 6: Update Main Barrel Export

**Export Strategy: Option 3 - Single `src/index.ts` with Explicit Exports**

**File: `src/index.ts`**

```typescript
// Utils
export { cn } from "./utils/cn";

// Icons (explicit exports for all 110+ icons)
export { default as Actions } from "./icons/actions";
export { default as Activity } from "./icons/activity";
export { default as AddLines } from "./icons/add-lines";
// ... all other icons
export * from "./icons/types"; // SvgProps, IconProps

// Hooks
export { useBoundingBox } from "./hooks/useBoundingBox";
export { useClickOutside } from "./hooks/useClickOutside";
export { useKeyPress, useEscape, useEnter } from "./hooks/useKeyPress";

// Components - Text (2 components)
export { default as Text } from "@/components/texts/Text";
export type { TextProps } from "@/components/texts/Text";
export { default as Truncated } from "@/components/texts/Truncated";
export type { TruncatedProps } from "@/components/texts/Truncated";

// Components - Buttons (11 components)
export { default as Button } from "@/components/buttons/Button";
export type { ButtonProps, SvgProps } from "@/components/buttons/Button";
export { default as IconButton } from "@/components/buttons/IconButton";
export type { IconButtonProps } from "@/components/buttons/IconButton";
export { default as CopyIconButton } from "@/components/buttons/CopyIconButton";
export type { CopyIconButtonProps } from "@/components/buttons/CopyIconButton";
export { default as CreateButton } from "@/components/buttons/CreateButton";
export type { CreateButtonProps } from "@/components/buttons/CreateButton";
export { default as AttachmentButton } from "@/components/buttons/AttachmentButton";
export type { AttachmentButtonProps } from "@/components/buttons/AttachmentButton";
export { default as FilterButton } from "@/components/buttons/FilterButton";
export type { FilterButtonProps } from "@/components/buttons/FilterButton";
export { default as SelectButton } from "@/components/buttons/SelectButton";
export type { SelectButtonProps } from "@/components/buttons/SelectButton";
export { default as MenuButton } from "@/components/buttons/MenuButton";
export type { MenuButtonProps } from "@/components/buttons/MenuButton";
export { default as LineItem } from "@/components/buttons/LineItem";
export type { LineItemProps } from "@/components/buttons/LineItem";
export { default as SidebarTab } from "@/components/buttons/SidebarTab";
export type { SidebarTabProps } from "@/components/buttons/SidebarTab";
export { default as Tag } from "@/components/buttons/Tag";
export type { TagProps } from "@/components/buttons/Tag";
```

**Benefits:**
- Single canonical import path: `import { X } from "@onyx/opal"`
- No confusion with paths like `"@onyx/opal/components"`
- Explicit control over what is exported
- Easy to see all public API in one file
- No intermediate index.ts files to maintain

---

## Migration Checklist (Per File)

### Before Migration
- [ ] Check file for `@/` imports
- [ ] Identify external dependencies
- [ ] Check for business logic
- [ ] Grep for usage in web: `grep -r "import.*from.*filename" web/src`

### During Migration
- [ ] Copy file to appropriate opal directory
- [ ] Update all imports:
  - [ ] Change `@/lib/utils` → `../../utils/cn` (full path, no index.ts)
  - [ ] Change `@/icons/` → `../../icons/icon-name` (full path)
  - [ ] Change `@/refresh-components/` → relative paths
- [ ] Remove any business logic
- [ ] Add JSDoc comments if missing
- [ ] Add explicit export to main `src/index.ts` (not intermediate index.ts)

### After Migration
- [ ] Run `cd web/lib/opal && bun run types:check`
- [ ] Run `cd web/lib/opal && bun run format`
- [ ] Test import in web: `import { X } from '@onyx/opal'` (ONLY this pattern)
- [ ] Update all web imports to use `@onyx/opal`
- [ ] Remove old file from web/src
- [ ] Run web typecheck: `cd web && bun run types:check`
- [ ] Commit with clear message

---

## Import Pattern Reference

### In Opal (Internal)

Use relative imports:
```typescript
// In components/buttons/Button.tsx
import { cn } from "../../utils/cn";
import { Text } from "../text/Text";
import type { SvgProps } from "../../icons/types";
```

### In Web (External)

**ONLY ONE CANONICAL IMPORT PATH:**
```typescript
// In web/src anywhere
import { Button, Text, Check, useClickOutside, cn } from "@onyx/opal";
```

**NOT ALLOWED:**
```typescript
// ❌ These paths will NOT work with Option 3
import { Button } from "@onyx/opal/components";
import { Button } from "@onyx/opal/components/buttons";
import { cn } from "@onyx/opal/utils";
```

All exports go through the single `src/index.ts` file.

---

## Execution Order

### Week 1: Foundation + Icons + Hooks

**Day 1-2:**
1. ✅ Set up opal directory structure
2. ✅ Add `cn` utility
3. ✅ Update opal package.json dependencies
4. ✅ Update web tailwind.config

**Day 3-4:**
5. ✅ Migrate icon types
6. ✅ Copy all 110+ icon files
7. ✅ Generate icon barrel exports
8. ✅ Test icon imports

**Day 5:**
9. ✅ Migrate 3 universal hooks
10. ✅ Create hooks barrel export
11. ✅ Test hook imports

### Week 2: Core Components

**Day 1:**
12. ✅ Migrate Text.tsx (already done)
13. ⏳ Migrate Truncated.tsx
14. ⏳ Add Truncated export to src/index.ts
15. ⏳ Test text components

**Day 2-3: Button Migration (11 files)**
16. ✅ Migrate Button.tsx (already done)
17. ⏳ Migrate IconButton.tsx
18. ⏳ Migrate CopyIconButton.tsx
19. ⏳ Migrate CreateButton.tsx
20. ⏳ Migrate AttachmentButton.tsx
21. ⏳ Migrate FilterButton.tsx
22. ⏳ Migrate SelectButton.tsx
23. ⏳ Migrate MenuButton.tsx
24. ⏳ Migrate LineItem.tsx (fix `bg-red` debug class)
25. ⏳ Migrate SidebarTab.tsx
26. ⏳ Migrate Tag.tsx
27. ⏳ Add all button exports to src/index.ts
28. ⏳ Test all button imports

**Day 4:**
29. ⏳ Update all web imports to use `@onyx/opal`
30. ⏳ Test web project after import updates
31. ⏳ Remove old files from web/src/refresh-components

**Day 5:**
32. ⏳ Final typecheck (opal + web)
33. ⏳ Final testing and cleanup
34. ⏳ Update documentation

---

## Success Criteria

### Technical
- [ ] All migrated files typecheck in opal
- [ ] All migrated files format correctly
- [ ] Web can import from `@onyx/opal` successfully
- [ ] Web typecheck passes
- [ ] No duplicate dependencies

### Organization
- [ ] Clear directory structure
- [ ] Consistent barrel exports
- [ ] All files have proper index.ts exports
- [ ] README documents usage

### Quality
- [ ] No business logic in opal
- [ ] Components are truly universal/reusable
- [ ] Props are well-typed
- [ ] JSDoc comments on complex functions

---

## Files Summary

### To Migrate (Estimated Count)

**Icons:** ~110 files ✅
**Hooks:** 3 files ✅
**Components:**
- Text: 2 files ✅
- Buttons: 2 files (start with core buttons)
- Utilities: 3 files ✅
- Loaders: 1 file ✅

**Total Phase 1:** ~121 files

### To Keep in Web

**Contexts:** 4 files ❌
**Domain Components:** 5+ files ❌
**App-Specific:** 20+ files ❌
**Complex Popovers:** 5+ files ❌
**Page Components:** 2+ files ❌
**Onboarding:** 10+ files ❌
**Formik Forms:** 5+ files ❌

**Total staying in web:** ~50+ files

---

## Risk Mitigation

### Risk: Breaking web during migration
**Mitigation:**
- Migrate one file at a time
- Keep old files until all imports updated
- Test after each migration
- Use git branches

### Risk: Import path confusion
**Mitigation:**
- Document import patterns clearly
- Use consistent barrel exports
- Provide examples in README

### Risk: Tailwind not working
**Mitigation:**
- Verify tailwind.config.js includes opal
- Test Tailwind classes compile
- Check JIT mode works

### Risk: Circular dependencies
**Mitigation:**
- Use barrel exports carefully
- Avoid re-exporting everything
- Keep dependency graph simple

---

## Commands Reference

```bash
# Typecheck opal
cd web/libs/opal && bun run types:check

# Format opal
cd web/libs/opal && bun run format

# Typecheck web
cd web && bun run types:check

# Search for imports in web
cd web && grep -r "import.*from.*@/icons" src/

# Generate icon exports
cd web/libs/opal/src/icons
for file in *.tsx; do
  name=$(basename "$file" .tsx | sed 's/-\([a-z]\)/\U\1/g' | sed 's/^\([a-z]\)/\U\1/')
  echo "export { default as ${name} } from './${file%.tsx}';"
done
```

---

## Next Steps - Current Phase: Button & Text Migration

### Immediate Next Steps (After Plan Review)

1. **Migrate Truncated.tsx**
   - Copy `web/src/refresh-components/texts/Truncated.tsx` → `web/lib/opal/src/components/texts/Truncated.tsx`
   - Update imports: `@/lib/utils` → `@/utils`
   - Ensure default export
   - Add to `src/index.ts`: `export { default as Truncated } from "@/components/texts/Truncated"`

2. **Migrate remaining 10 button components**
   - Follow same pattern as Button.tsx (already migrated)
   - Fix LineItem.tsx `bg-red` debug class issue
   - All components already use proper patterns

3. **Update src/index.ts with all new exports**
   - Add Truncated export
   - Add all 10 button exports (IconButton, CopyIconButton, etc.)
   - Keep alphabetical order within each section

4. **Test and verify**
   - Run `cd web/lib/opal && bun run types:check`
   - Run `cd web && bun run types:check`
   - Verify all imports work

5. **Update web project imports** (separate phase after migration)
   - Find all usages: `grep -r "from.*@/refresh-components/buttons" web/src/`
   - Find all usages: `grep -r "from.*@/refresh-components/texts" web/src/`
   - Replace with `from "@onyx/opal"`

6. **Clean up old files**
   - Delete `web/src/refresh-components/buttons/` (after verifying web still works)
   - Delete `web/src/refresh-components/texts/` (after verifying web still works)

---

## Detailed Migration Checklist - Buttons & Text

### Text Components (1 remaining)

- [x] Text.tsx - Already migrated ✅
- [ ] Truncated.tsx
  - [ ] Copy file to opal/src/components/texts/
  - [ ] Change `@/lib/utils` → `@/utils`
  - [ ] Verify default export
  - [ ] Add to src/index.ts
  - [ ] Typecheck

### Button Components (10 remaining)

- [x] Button.tsx - Already migrated ✅
- [ ] IconButton.tsx
  - [ ] Copy to opal/src/components/buttons/
  - [ ] Update imports (`@/lib/utils` → `@/utils`, `@/refresh-components/texts/Text` → `@/components/texts/Text`)
  - [ ] Verify default export
  - [ ] Add to src/index.ts
- [ ] CopyIconButton.tsx
  - [ ] Same steps as above
  - [ ] Update relative import `./IconButton` → `@/components/buttons/IconButton`
- [ ] CreateButton.tsx
  - [ ] Same steps as above
  - [ ] Update `@/refresh-components/buttons/Button` → `@/components/buttons/Button`
- [ ] AttachmentButton.tsx
  - [ ] Same steps as above
  - [ ] Update Text, Truncated, IconButton imports
- [ ] FilterButton.tsx
  - [ ] Same steps as above
  - [ ] Update relative import `./IconButton`
- [ ] SelectButton.tsx
  - [ ] Same steps as above
  - [ ] Update Text import
- [ ] MenuButton.tsx
  - [ ] Same steps as above
  - [ ] Update Truncated import
- [ ] LineItem.tsx
  - [ ] Same steps as above
  - [ ] **FIX:** Remove or replace `bg-red` debug class (line 46)
  - [ ] Update Text, Truncated imports
- [ ] SidebarTab.tsx
  - [ ] Same steps as above
  - [ ] Update Truncated import
  - [ ] Update `@/refresh-components/SimpleTooltip` (need to check if SimpleTooltip is migrated)
- [ ] Tag.tsx
  - [ ] Same steps as above
  - [ ] Update Text import

### After All Components Migrated

- [ ] Run opal typecheck: `cd web/lib/opal && bun run types:check`
- [ ] Run web typecheck: `cd web && bun run types:check`
- [ ] Verify all exports in src/index.ts
- [ ] Test imports work: create test file in web importing all components

---

## Notes

- Be conservative: when in doubt, keep it in web
- Focus on truly universal primitives
- Document everything as we go
- Update this plan based on learnings
- Icons are safe to migrate (no logic)
- Hooks require careful review for dependencies
- Components need the most scrutiny
- **All 11 buttons are confirmed universal** - zero app-specific logic found
- **SimpleTooltip dependency** - SidebarTab.tsx uses it, need to check if it's already in opal or needs migration
