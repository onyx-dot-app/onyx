# Cards

This directory contains feature-specific card components.

Cards are self-contained UI components that display information about a specific entity (e.g., an agent, a document set, a connector) in a visually distinct, bounded container. They typically include:

- Entity identification (name, avatar, icon)
- Summary information
- Quick actions (buttons, menus)

## Guidelines

- Each card should be focused on a single entity type
- Cards should be reusable across different pages/contexts
- Keep card-specific logic within the card component
- Use shared components from `@/refresh-components` for common UI elements
