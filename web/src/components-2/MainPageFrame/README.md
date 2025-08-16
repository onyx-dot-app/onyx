# MainPageFrame Component

The `MainPageFrame` component is the main layout wrapper that provides the foundational structure for chat and search pages. It orchestrates the sidebar, header, and main content areas with seamless animations and responsive behavior.

## Overview

The MainPageFrame component serves as the primary layout container that manages the overall page structure. It coordinates the positioning and visibility of the sidebar, header, and main content areas, ensuring smooth transitions and proper spacing across different screen sizes.

## Key Features

### Layout Orchestration
- **Sidebar Management**: Controls sidebar visibility and positioning with smooth animations
- **Header Integration**: Positions the header component with proper spacing
- **Content Area**: Provides the main content area that adapts to sidebar state
- **Logo Positioning**: Manages the collapsible logo placement for seamless sidebar integration

### Sidebar Integration
The MainPageFrame component manages sidebar behavior through the `useSidebar` hook:

```tsx
const {
  sidebarElementRef,
  sidebarPinned,
  sidebarVisible,
  toggleSidebarPinned,
} = useSidebar();
```

#### Sidebar Behavior
- **Visibility Control**: Manages sidebar show/hide states with opacity transitions
- **Smooth Animations**: Provides seamless transitions when opening/closing the sidebar
- **Keyboard Shortcuts**: Integrates sidebar toggle functionality (Ctrl+E / Cmd+E)
- **Responsive Positioning**: Adjusts sidebar width and positioning based on visibility state

### Logo Integration
The component includes a collapsible logo that's positioned outside the header for seamless sidebar animation:

```tsx
<div className="fixed top-[12px] left-[16px] z-30">
  <Link href="chat">
    <CollapsibleLogo />
  </Link>
</div>
```

## Mobile vs Desktop Rendering

### Desktop Behavior
- **Full Sidebar Support**: Complete sidebar functionality with hover interactions
- **Keyboard Shortcuts**: Full keyboard shortcut support for sidebar toggling
- **Smooth Animations**: Comprehensive transition effects for all layout changes
- **Spacious Layout**: Optimized for larger screens with more screen real estate

### Mobile Behavior
- **Simplified Sidebar**: Reduced sidebar functionality for mobile constraints
- **Touch-Optimized**: Larger touch targets and mobile-friendly interactions
- **Compact Layout**: Condensed spacing and layout to fit mobile viewports
- **Reduced Animations**: Streamlined transitions for better mobile performance

## Integration Points

### Sidebar Provider
The MainPageFrame component integrates with the `SidebarProvider` to receive real-time updates about sidebar visibility and manage the overall layout state.

### Chat Context
Accesses chat-related data including:
- Chat sessions and conversation history
- Folder structure and organization
- User preferences and settings

### Header Component
Coordinates with the Header component to ensure proper positioning and spacing when the sidebar state changes.

## Usage

The MainPageFrame component is typically used in layout components for chat and search pages:

```tsx
import MainPageFrame from "@/components-2/MainPageFrame";

// In layout or page component
<MainPageFrame>
  {/* Main content goes here */}
</MainPageFrame>
```
