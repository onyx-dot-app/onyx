// @onyx-ai/api-types — shared, framework-agnostic Onyx domain types for web + mobile.
//
// Contents are owned by: docs/plans/2026-05-30-mobile-app/02-shared-packages.md
// Hand-port (no codegen for v1) from:
//   web/src/lib/types.ts            (User, UserRole, ValidSources, ChatSessionSummary, ThemePreference, ...)
//   web/src/lib/agents/types.ts
//   web/src/lib/search/interfaces.ts
//   web/src/lib/tools/interfaces.ts
//   web/src/app/app/interfaces.ts   (Message tree: nodeId/parentNodeId/childrenNodeIds/...)
//   web/src/app/app/services/streamingModels.ts (PacketType + 50+ packet types)
//
// This is a source-only internal package: consumers import TS directly via the
// Bun-workspace symlink; there is no build step.

export {};
