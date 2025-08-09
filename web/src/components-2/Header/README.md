# Header Component

The `Header` component is the main navigation header used across the chat and search pages of the application. It provides a consistent top-level interface for users to navigate between different modes and access user-specific functionality.

## Overview

The Header component serves as the primary navigation element that appears at the top of both the chat and search pages. It features a mode selector dropdown and user account controls, with intelligent positioning that adapts to sidebar visibility states.

## Key Features

### Mode Selection Dropdown
- **Search Mode**: Quick document search functionality
- **Chat Mode**: Conversation and research with follow-up questions
- **Visual Indicators**: Each mode has its own icon (MagnifyingIcon for Search, ChatIcon for Chat)
- **Smooth Navigation**: Clicking a mode navigates to the appropriate page (`/search` or `/chat`)

### User Account Controls
- **User Dropdown**: Access to user settings and account management
- **Settings Modal**: Comprehensive user preferences and configuration
- **LLM Provider Management**: Model selection and configuration
- **Federated Connectors**: OAuth status and connector management

### Responsive Sidebar Integration
The Header component intelligently responds to sidebar visibility states through the `useSidebar` hook:

```tsx
const { sidebarVisible } = useSidebar();
```

#### Sidebar Visibility Behavior
- **When Sidebar Visible**: Header content shifts to accommodate the sidebar
- **When Sidebar Hidden**: Header content shifts to utilize the available space
- **Smooth Transitions**: Animated transitions for seamless visual feedback

```tsx
<div
  className={`flex flex-1 transition-transform duration-300 ease-in-out ${
    sidebarVisible ? "translate-x-0" : "translate-x-[130px]"
  }`}
>
```

## Mobile vs Desktop Rendering

### Desktop Behavior
- **Full Feature Set**: All dropdown options and user controls are available
- **Sidebar Responsiveness**: Header adapts to sidebar visibility changes
- **Hover Interactions**: Full hover effects and dropdown interactions
- **Spacious Layout**: Optimized for larger screens with more screen real estate

### Mobile Behavior
- **Simplified Interface**: Streamlined layout for smaller screens
- **Touch-Optimized**: Larger touch targets for mobile interaction
- **Reduced Sidebar Dependencies**: Less reliance on sidebar state due to mobile layout constraints
- **Compact Design**: Condensed spacing and layout to fit mobile viewports

## Integration Points

### Sidebar Provider
The Header component integrates with the `SidebarProvider` to receive real-time updates about sidebar visibility. This allows the header to adjust its positioning dynamically as users interact with the sidebar.

### Chat Context
Accesses chat-related configuration including:
- LLM providers and model options
- CC pairs for connector configurations
- User preferences and settings

### User Management
- User authentication state
- User preferences and settings
- Model selection and configuration
- OAuth connector management

## Usage

The Header component is typically used in layout components for chat and search pages:

```tsx
import { Header } from "@/components-2/Header";

// In layout or page component
<Header />
```
