# AGENTS.md

This file provides guidance to AI agents when working on the web application within this directory.

## Important Notes

- **The development server is already running** at a dynamically allocated port. Do NOT run `npm run dev` yourself.
- **We do NOT use a `src` directory** - all code lives directly in the root folders (`app/`, `components/`, `lib/`, etc.)
- If the app needs pre-computation (data processing, API calls, etc.), create a bash or python script called `prepare.sh`/`prepare.py` at the root of this directory
- **CRITICAL: Create small, modular components** - Do NOT write everything in `page.tsx`. Break your UI into small, reusable components in the `components/` directory. Each component should have a single responsibility and be in its own file.

## Data Preparation Scripts

**CRITICAL: Always re-run data scripts after modifying them.**

If a `prepare.sh` or `prepare.py` script exists at the root of this directory, it is responsible for generating/loading data that the frontend consumes. 

### When to Run the Script

You MUST run the data preparation script:
1. **After creating** the script for the first time
2. **After modifying** the script logic (new data sources, changed processing, etc.)
3. **After updating** any data files the script reads from
4. **Before testing** the frontend if you're unsure if data is fresh

### How to Run

```bash
# For bash scripts
bash prepare.sh

# For python scripts
python prepare.py
```

### Common Mistake

❌ **Updating the script but forgetting to run it** - This leaves stale data in place and the frontend won't reflect your changes. Always run the script immediately after modifying it.

## Commands

```bash
npm run dev      # Start development server (DO NOT RUN - already running)
npm run lint     # Run ESLint
```

## Architecture

This is a **Next.js 16.1.1** application using the **App Router** with **React 19** and **TypeScript**. It serves as a component showcase/template built on shadcn/ui.

### File Organization Philosophy

**Prioritize small, incremental file writes.** Break your application into many small components rather than monolithic page files.

#### Component Organization

```
components/
├── dashboard/           # Feature-specific components
│   ├── stats-card.tsx
│   ├── activity-feed.tsx
│   └── recent-items.tsx
├── charts/             # Chart components
│   ├── line-chart.tsx
│   ├── bar-chart.tsx
│   └── pie-chart.tsx
├── data/               # Data display components
│   ├── data-table.tsx
│   ├── filter-bar.tsx
│   └── sort-controls.tsx
└── layout/             # Layout components
    ├── header.tsx
    ├── sidebar.tsx
    └── footer.tsx
```

#### Page Structure

Pages (`app/page.tsx`) should be **thin orchestration layers** that compose components:

```typescript
// ✅ GOOD - page.tsx is just composition
import { StatsCard } from "@/components/dashboard/stats-card";
import { ActivityFeed } from "@/components/dashboard/activity-feed";
import { RecentItems } from "@/components/dashboard/recent-items";

export default function DashboardPage() {
  return (
    <div className="container py-6 space-y-6">
      <h1 className="text-3xl font-bold">Dashboard</h1>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatsCard title="Total Users" value={1234} />
        <StatsCard title="Active Sessions" value={56} />
        <StatsCard title="Revenue" value="$12,345" />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ActivityFeed />
        <RecentItems />
      </div>
    </div>
  );
}

// ❌ BAD - Everything in page.tsx (500+ lines of mixed logic)
export default function DashboardPage() {
  // ... 500 lines of component logic, state, handlers, JSX ...
}
```

#### Component Granularity

Create a new component file when:
- A UI section has distinct functionality (e.g., `user-profile-card.tsx`)
- Logic exceeds ~50-100 lines
- A pattern is reused 2+ times
- Testing/maintenance would benefit from isolation

**Example: Dashboard Feature**

Instead of writing everything in `app/page.tsx`:

```typescript
// components/dashboard/stats-card.tsx
export function StatsCard({ title, value, trend }: StatsCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        {trend && <p className="text-xs text-muted-foreground">{trend}</p>}
      </CardContent>
    </Card>
  );
}

// components/dashboard/activity-feed.tsx
export function ActivityFeed() {
  // Activity feed logic here
}

// components/dashboard/recent-items.tsx
export function RecentItems() {
  // Recent items logic here
}
```

#### Benefits of Small Components

1. **Incremental Development**: Write one component at a time, test, iterate
2. **Better Diffs**: Smaller files = clearer git diffs and easier reviews
3. **Reusability**: Components can be imported across pages
4. **Maintainability**: Easier to locate and fix issues
5. **Hot Reload Efficiency**: Changes to small files reload faster
6. **Parallel Development**: Multiple features can be worked on independently

### Tech Stack

- **Framework**: Next.js 16.1.1 with App Router
- **React**: React 19
- **Language**: TypeScript
- **Styling**: Tailwind CSS v4 with CSS variables in OKLCH color space
- **Charts**: recharts for data visualization
- **UI Components**: shadcn/ui (53 components) built on Radix UI primitives
- **Variants**: class-variance-authority (CVA) for component variants
- **Class Merging**: `cn()` utility in `lib/utils.ts` (clsx + tailwind-merge)
- **Theme**: Dark mode enforced (via `dark` class on `<html>`)

### Key Directories

- `app/` - Next.js App Router pages and layouts
- `components/ui/` - shadcn/ui component library (Button, Card, Dialog, etc.)
- `components/` - App-specific components
- `hooks/` - Custom React hooks (e.g., `use-mobile.ts`)
- `lib/` - Utilities (`cn()` function)

### Component Patterns

- **Compound Components**: Components like `DropdownMenu`, `Dialog`, `Select` export multiple sub-components (Trigger, Content, Item)
- **Variants via CVA**: Use `variants` prop for size/style variations (e.g., `buttonVariants`)
- **Radix UI Primitives**: UI components wrap Radix for accessibility

### Path Aliases

All imports use `@/` alias (e.g., `@/components/ui/button`, `@/lib/utils`)

### shadcn/ui Configuration

Located in `components.json`:

- Style: `radix-nova`
- RSC enabled
- Icons: lucide-react

### Theme Variables

Global CSS variables defined in `app/globals.css` control colors, radius, and spacing. **Dark mode is enforced site-wide** via the `dark` class on the `<html>` element in `app/layout.tsx`. All styling should assume dark mode is active.

### Dark Mode Priority

- **Dark mode is the default and only theme** - do not design for light mode
- The `dark` class is permanently set on `<html>` in `layout.tsx`
- Use dark-appropriate colors: `bg-background`, `text-foreground`, etc.
- Ensure sufficient contrast for dark backgrounds
- Test all components in dark mode only

## Styling Guidelines

### CRITICAL: Use Only shadcn/ui Components

**MINIMIZE freestyling and creating custom components.** This application uses a complete, professionally designed component library (shadcn/ui). You MUST use the existing components from `components/ui/` for most UI needs.

#### Available shadcn/ui Components

All components are in `components/ui/`. Import using `@/components/ui/component-name`.

**Layout & Structure:**

- `Card` (`card.tsx`) - Content containers with CardHeader, CardTitle, CardDescription, CardContent, CardFooter
- `Separator` (`separator.tsx`) - Horizontal/vertical dividers
- `Tabs` (`tabs.tsx`) - Tabbed interfaces with Tabs, TabsList, TabsTrigger, TabsContent
- `ScrollArea` (`scroll-area.tsx`) - Styled scrollable regions
- `Resizable` (`resizable.tsx`) - Resizable panel layouts
- `Drawer` (`drawer.tsx`) - Bottom/side drawer overlays
- `Sidebar` (`sidebar.tsx`) - Application sidebar layout
- `AspectRatio` (`aspect-ratio.tsx`) - Maintain aspect ratios

**Forms & Inputs:**

- `Button` (`button.tsx`) - Primary, secondary, destructive, outline, ghost, link variants
- `ButtonGroup` (`button-group.tsx`) - Group of related buttons
- `Input` (`input.tsx`) - Text inputs with various states
- `InputGroup` (`input-group.tsx`) - Input with addons/icons
- `Textarea` (`textarea.tsx`) - Multi-line text input
- `Checkbox` (`checkbox.tsx`) - Checkboxes with indeterminate state
- `RadioGroup` (`radio-group.tsx`) - Radio button groups
- `Switch` (`switch.tsx`) - Toggle switches
- `Select` (`select.tsx`) - Dropdown select menus
- `NativeSelect` (`native-select.tsx`) - Native HTML select
- `Combobox` (`combobox.tsx`) - Autocomplete select with search
- `Command` (`command.tsx`) - Command palette/search interface
- `Field` (`field.tsx`) - Form field wrapper with label and error
- `Label` (`label.tsx`) - Form labels with proper accessibility
- `Slider` (`slider.tsx`) - Range sliders
- `Calendar` (`calendar.tsx`) - Date picker calendar
- `Toggle` (`toggle.tsx`) - Toggle button
- `ToggleGroup` (`toggle-group.tsx`) - Group of toggle buttons

**Navigation:**

- `NavigationMenu` (`navigation-menu.tsx`) - Complex navigation menus
- `Menubar` (`menubar.tsx`) - Application menu bar
- `Breadcrumb` (`breadcrumb.tsx`) - Breadcrumb navigation
- `Pagination` (`pagination.tsx`) - Page navigation controls

**Feedback & Overlays:**

- `Dialog` (`dialog.tsx`) - Modal dialogs
- `AlertDialog` (`alert-dialog.tsx`) - Confirmation dialogs
- `Sheet` (`sheet.tsx`) - Side sheets/panels
- `Popover` (`popover.tsx`) - Floating popovers
- `HoverCard` (`hover-card.tsx`) - Hover-triggered cards
- `Tooltip` (`tooltip.tsx`) - Tooltips on hover
- `Sonner` (`sonner.tsx`) - Toast notifications
- `Alert` (`alert.tsx`) - Static alert messages
- `Progress` (`progress.tsx`) - Progress bars
- `Skeleton` (`skeleton.tsx`) - Loading skeletons
- `Spinner` (`spinner.tsx`) - Loading spinners
- `Empty` (`empty.tsx`) - Empty state placeholder

**Menus & Dropdowns:**

- `DropdownMenu` (`dropdown-menu.tsx`) - Dropdown menus with submenus
- `ContextMenu` (`context-menu.tsx`) - Right-click context menus

**Data Display:**

- `Table` (`table.tsx`) - Data tables with Table, TableHeader, TableBody, TableRow, TableCell, etc.
- `Badge` (`badge.tsx`) - Status badges and tags
- `Avatar` (`avatar.tsx`) - User avatars with fallbacks
- `Accordion` (`accordion.tsx`) - Collapsible content sections
- `Collapsible` (`collapsible.tsx`) - Simple collapse/expand
- `Carousel` (`carousel.tsx`) - Image/content carousels
- `Item` (`item.tsx`) - List item component
- `Kbd` (`kbd.tsx`) - Keyboard shortcut display

**Data Visualization:**

- `Chart` (`chart.tsx`) - Chart wrapper with ChartContainer, ChartTooltip, ChartTooltipContent, ChartLegend, ChartLegendContent

### Component Usage Principles

#### 1. **Never Create Custom Components**

```typescript
// ❌ WRONG - Do not create freestyle components
function CustomCard({ title, children }) {
  return (
    <div className="rounded-lg border p-4">
      <h3 className="font-bold">{title}</h3>
      {children}
    </div>
  );
}

// ✅ CORRECT - Use shadcn Card
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";

function MyComponent() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Title</CardTitle>
      </CardHeader>
      <CardContent>Content here</CardContent>
    </Card>
  );
}
```

#### 2. **Use Component Variants, Don't Style Directly**

```typescript
// ❌ WRONG - Applying custom Tailwind classes
<button className="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">
  Click me
</button>

// ✅ CORRECT - Use Button variants
import { Button } from "@/components/ui/button";

<Button variant="default">Click me</Button>
<Button variant="destructive">Delete</Button>
<Button variant="outline">Cancel</Button>
<Button variant="ghost">Subtle Action</Button>
<Button size="sm">Small</Button>
<Button size="lg">Large</Button>
```

#### 3. **Compose Compound Components**

Many shadcn components export multiple sub-components. Use them as designed:

```typescript
// ✅ Dropdown Menu Composition
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";

<DropdownMenu>
  <DropdownMenuTrigger asChild>
    <Button variant="outline">Options</Button>
  </DropdownMenuTrigger>
  <DropdownMenuContent>
    <DropdownMenuLabel>Actions</DropdownMenuLabel>
    <DropdownMenuSeparator />
    <DropdownMenuItem>Edit</DropdownMenuItem>
    <DropdownMenuItem>Delete</DropdownMenuItem>
  </DropdownMenuContent>
</DropdownMenu>
```

#### 4. **Use Layout Components for Structure**

```typescript
// ✅ Use Card for content sections
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";

<Card>
  <CardHeader>
    <CardTitle>Dashboard</CardTitle>
    <CardDescription>Overview of your data</CardDescription>
  </CardHeader>
  <CardContent>
    {/* Your content */}
  </CardContent>
  <CardFooter>
    <Button>Action</Button>
  </CardFooter>
</Card>
```

### Styling Rules

#### 1. **Spacing & Layout**

Use Tailwind's utility classes for spacing, but stick to the design system:

- Gap: `gap-2`, `gap-4`, `gap-6`, `gap-8`
- Padding: `p-2`, `p-4`, `p-6`, `p-8`
- Margins: Prefer `gap` and `space-y-*` over margins

#### 2. **Colors**

All colors come from CSS variables in `app/globals.css`. Use semantic color classes:

- `bg-background`, `bg-foreground`
- `bg-card`, `text-card-foreground`
- `bg-primary`, `text-primary-foreground`
- `bg-secondary`, `text-secondary-foreground`
- `bg-muted`, `text-muted-foreground`
- `bg-accent`, `text-accent-foreground`
- `bg-destructive`, `text-destructive-foreground`
- `border-border`, `border-input`
- `ring-ring`

**DO NOT use arbitrary color values** like `bg-blue-500` or `text-red-600`.

#### **CRITICAL: Color Contrast Pairing Rules**

**Always pair background colors with their matching foreground colors.** The color system uses paired variables where each background has a corresponding text color designed for proper contrast.

| Background Class | Text Class to Use | Description |
|-----------------|-------------------|-------------|
| `bg-background` | `text-foreground` | Main page background |
| `bg-card` | `text-card-foreground` | Card containers |
| `bg-primary` | `text-primary-foreground` | Primary buttons/accents |
| `bg-secondary` | `text-secondary-foreground` | Secondary elements |
| `bg-muted` | `text-muted-foreground` | Muted/subtle areas |
| `bg-accent` | `text-accent-foreground` | Accent highlights |
| `bg-destructive` | `text-destructive-foreground` | Error/delete actions |

**Examples:**

```typescript
// ✅ CORRECT - Matching background and foreground pairs
<div className="bg-card text-card-foreground">Content</div>
<Button className="bg-primary text-primary-foreground">Click</Button>
<div className="bg-muted text-muted-foreground">Subtle text</div>

// ❌ WRONG - Mismatched colors causing contrast issues
<div className="bg-background text-background">Invisible text!</div>
<div className="bg-card text-foreground">May have poor contrast</div>
<Button className="bg-primary text-primary">White on white!</Button>
```

**Key Rules:**

1. **Never use the same color for background and text** (e.g., `bg-foreground text-foreground`)
2. **Always use the `-foreground` variant for text** when using a colored background
3. **For text on `bg-background`**, use `text-foreground` (primary) or `text-muted-foreground` (secondary)
4. **Test visually** - if text is hard to read, you have a contrast problem

#### 3. **Typography**

Use Tailwind text utilities (no separate Typography component):

- Headings: `text-xl font-semibold`, `text-2xl font-bold`, etc.
- Body: `text-sm`, `text-base`
- Secondary text: `text-muted-foreground`
- Use semantic HTML: `<h1>`, `<h2>`, `<p>`, etc.
- **Always wrap text** - Use `max-w-prose` or `max-w-xl` for readable line lengths
- **Prevent overflow** - Use `break-words` or `truncate` for long text that might overflow containers

#### 4. **Responsive Design**

Use Tailwind's responsive prefixes:

```typescript
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
  {/* Responsive grid */}
</div>
```

#### 5. **Icons**

Use Lucide React icons (already configured):

```typescript
import { Check, X, ChevronDown, User } from "lucide-react";

<Button>
  <Check className="mr-2 h-4 w-4" />
  Confirm
</Button>
```

### Data Visualization

For charts and data visualization, use the **shadcn/ui Chart components** (`@/components/ui/chart`) which wrap recharts with consistent theming. Charts should be **elegant, informative, and digestible at a glance**.

#### Chart Design Principles

1. **Clarity over complexity** - A chart should communicate ONE key insight immediately
2. **Minimal visual noise** - Remove anything that doesn't add information
3. **Consistent styling** - Use `ChartConfig` for colors, not arbitrary values
4. **Responsive** - Always use `ChartContainer` (includes ResponsiveContainer)
5. **Accessible** - Use `ChartTooltip` with `ChartTooltipContent` for proper styling

#### Chart Type Selection

| Data Type | Recommended Chart | Use Case |
|-----------|-------------------|----------|
| Trend over time | `LineChart` or `AreaChart` | Stock prices, user growth, metrics over days/months |
| Comparing categories | `BarChart` | Revenue by product, users by region |
| Part of whole | `PieChart` or `RadialBarChart` | Market share, budget allocation |
| Distribution | `BarChart` (horizontal) | Survey responses, rating distribution |
| Correlation | `ScatterChart` | Price vs. quality, age vs. income |

#### shadcn/ui Chart Components

Always import from the shadcn chart component:

```typescript
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { LineChart, Line, XAxis, YAxis, CartesianGrid } from "recharts";
```

#### ChartConfig - Define Colors and Labels

The `ChartConfig` object defines colors and labels for your data series. This ensures consistent theming:

```typescript
const chartConfig = {
  revenue: {
    label: "Revenue",
    color: "var(--chart-1)",
  },
  expenses: {
    label: "Expenses", 
    color: "var(--chart-2)",
  },
} satisfies ChartConfig;
```

#### Basic Line Chart Template

```typescript
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { LineChart, Line, XAxis, YAxis, CartesianGrid } from "recharts";

const chartConfig = {
  value: {
    label: "Value",
    color: "var(--chart-1)",
  },
} satisfies ChartConfig;

<ChartContainer config={chartConfig} className="h-[300px] w-full">
  <LineChart data={data} accessibilityLayer>
    <CartesianGrid vertical={false} />
    <XAxis
      dataKey="month"
      tickLine={false}
      axisLine={false}
      tickMargin={8}
    />
    <YAxis tickLine={false} axisLine={false} tickMargin={8} />
    <ChartTooltip content={<ChartTooltipContent />} />
    <Line
      type="monotone"
      dataKey="value"
      stroke="var(--color-value)"
      strokeWidth={2}
      dot={false}
    />
  </LineChart>
</ChartContainer>
```

#### Bar Chart with Multiple Series

```typescript
const chartConfig = {
  revenue: {
    label: "Revenue",
    color: "var(--chart-1)",
  },
  expenses: {
    label: "Expenses",
    color: "var(--chart-2)",
  },
} satisfies ChartConfig;

<ChartContainer config={chartConfig} className="h-[300px] w-full">
  <BarChart data={data} accessibilityLayer>
    <CartesianGrid vertical={false} />
    <XAxis dataKey="month" tickLine={false} axisLine={false} tickMargin={8} />
    <YAxis tickLine={false} axisLine={false} tickMargin={8} />
    <ChartTooltip content={<ChartTooltipContent />} />
    <ChartLegend content={<ChartLegendContent />} />
    <Bar dataKey="revenue" fill="var(--color-revenue)" radius={4} />
    <Bar dataKey="expenses" fill="var(--color-expenses)" radius={4} />
  </BarChart>
</ChartContainer>
```

#### Pie/Donut Chart

```typescript
const chartConfig = {
  desktop: { label: "Desktop", color: "var(--chart-1)" },
  mobile: { label: "Mobile", color: "var(--chart-2)" },
  tablet: { label: "Tablet", color: "var(--chart-3)" },
} satisfies ChartConfig;

<ChartContainer config={chartConfig} className="h-[300px] w-full">
  <PieChart>
    <ChartTooltip content={<ChartTooltipContent hideLabel />} />
    <Pie
      data={data}
      dataKey="value"
      nameKey="name"
      innerRadius={60}  // Remove for solid pie, keep for donut
      strokeWidth={5}
    />
    <ChartLegend content={<ChartLegendContent nameKey="name" />} />
  </PieChart>
</ChartContainer>
```

#### Chart Styling Rules

**Colors (use CSS variables from globals.css):**
- `var(--chart-1)` through `var(--chart-5)` - Primary chart colors
- `var(--primary)` - For single-series emphasis
- `var(--muted)` - For de-emphasized data

**Color References in Charts:**
- In `ChartConfig`: Use `color: "var(--chart-1)"`
- In chart elements: Use `fill="var(--color-keyname)"` or `stroke="var(--color-keyname)"`
- The `keyname` matches the key in your `ChartConfig`

**Visual Cleanup:**
- Set `tickLine={false}` and `axisLine={false}` on axes for cleaner look
- Use `vertical={false}` on `CartesianGrid` for horizontal-only grid lines
- Use `dot={false}` on line charts unless individual points matter
- Add `radius={4}` to bars for rounded corners
- Limit to 3-5 data series maximum per chart

**Avoid:**
- ❌ 3D effects
- ❌ More than 5-6 colors in one chart
- ❌ Legends with more than 5 items (simplify the data instead)
- ❌ Dual Y-axes (confusing - use two separate charts)
- ❌ Pie charts with more than 5-6 slices
- ❌ Custom tooltip styling - use `ChartTooltipContent`

#### Fallback to Raw Recharts

If shadcn/ui Chart components don't support a specific chart type (e.g., ScatterChart, ComposedChart, RadarChart), you can use recharts directly:

```typescript
import { ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

<ResponsiveContainer width="100%" height={300}>
  <ScatterChart>
    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
    <XAxis dataKey="x" stroke="var(--muted-foreground)" fontSize={12} tickLine={false} axisLine={false} />
    <YAxis dataKey="y" stroke="var(--muted-foreground)" fontSize={12} tickLine={false} axisLine={false} />
    <Tooltip 
      contentStyle={{ 
        backgroundColor: "var(--card)", 
        border: "1px solid var(--border)", 
        borderRadius: "6px" 
      }} 
    />
    <Scatter data={data} fill="var(--chart-1)" />
  </ScatterChart>
</ResponsiveContainer>
```

**When using raw recharts:**
- Still use CSS variables for colors (`var(--chart-1)`, etc.)
- Match styling to shadcn conventions (tickLine={false}, axisLine={false})
- Style tooltips to match the design system

#### Data Accuracy Checklist

Before displaying a chart, verify:
- [ ] `ChartConfig` keys match your data's `dataKey` values
- [ ] Data values are correctly mapped to the right axes
- [ ] Axis labels match the data units (%, $, count, etc.)
- [ ] Time series data is sorted chronologically
- [ ] No missing data points that would break the visualization
- [ ] `ChartTooltip` with `ChartTooltipContent` is included
- [ ] Chart title/context makes the insight clear

### Common Patterns

#### Loading States

```typescript
import { Skeleton } from "@/components/ui/skeleton";

{isLoading ? (
  <Skeleton className="h-12 w-full" />
) : (
  <Content />
)}
```

#### Empty States

```typescript
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription, EmptyMedia } from "@/components/ui/empty";
import { Inbox } from "lucide-react";

<Empty>
  <EmptyHeader>
    <EmptyMedia variant="icon">
      <Inbox />
    </EmptyMedia>
    <EmptyTitle>No data available</EmptyTitle>
    <EmptyDescription>
      There's nothing to display yet. Add some items to get started.
    </EmptyDescription>
  </EmptyHeader>
</Empty>
```

#### Interactive Lists

```typescript
import { ScrollArea } from "@/components/ui/scroll-area";
import { ItemGroup, Item, ItemContent, ItemTitle, ItemDescription, ItemMedia } from "@/components/ui/item";
import { FileText } from "lucide-react";

<ScrollArea className="h-[400px]">
  <ItemGroup>
    {items.map((item) => (
      <Item key={item.id} variant="outline">
        <ItemMedia variant="icon">
          <FileText />
        </ItemMedia>
        <ItemContent>
          <ItemTitle>{item.name}</ItemTitle>
          <ItemDescription>{item.description}</ItemDescription>
        </ItemContent>
      </Item>
    ))}
  </ItemGroup>
</ScrollArea>
```

#### Form Fields

```typescript
import { Field, FieldLabel, FieldDescription, FieldError, FieldGroup } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

<FieldGroup>
  <Field>
    <FieldLabel>Email</FieldLabel>
    <Input type="email" placeholder="you@example.com" />
    <FieldDescription>We'll never share your email.</FieldDescription>
  </Field>
  <Field>
    <FieldLabel>Password</FieldLabel>
    <Input type="password" />
    <FieldError>Password must be at least 8 characters.</FieldError>
  </Field>
  <Button type="submit">Sign up</Button>
</FieldGroup>
```

### What NOT To Do

❌ **Don't create custom styled divs when a component exists**
❌ **Don't use arbitrary Tailwind colors** (use CSS variables)
❌ **Don't import UI libraries** like Material-UI, Ant Design, etc.
❌ **Don't use inline styles** except for dynamic values
❌ **Don't create custom form inputs** (use Field, Input, Select, etc. from components/ui)
❌ **Don't add new dependencies** without checking if shadcn covers it
❌ **Don't write everything in page.tsx** - break into separate component files
❌ **Don't design for light mode** - this site is dark mode only
❌ **Don't use `dark:` variants** - dark mode is always active, use base classes

### Development Workflow

1. **Plan the component structure** - Identify logical UI sections before writing code
2. **Create components incrementally** - Write one small component file at a time
3. **Test each component** - Verify it works before moving to the next
4. **Compose in page.tsx** - Import and arrange your components in the page
5. **Iterate** - Refine individual components without touching others

### Summary

This application has a **complete, production-ready component library**. Your job is to:
1. **Compose** shadcn/ui components (from `components/ui/`)
2. **Create small, focused component files** (in `components/`)
3. **Keep pages thin** - pages should orchestrate components, not contain implementation

Think of yourself as assembling LEGO blocks—all the UI pieces you need already exist in `components/ui/`, and you create small, organized structures by composing them into feature-specific components.
