import { SourceIcon } from "@/components/message/sources/SourceIcon";
import type { MobileSource } from "@/lib/sources/sourceMetadata";
import type { SwitchListItem } from "./SwitchList";

// ---------------------------------------------------------------------------
// SourceRow — builds a SwitchList item for a single source.
//
// Implemented as a `toSourceItem(source, isEnabled, onToggle)` helper rather
// than a component: the actions popover maps `MobileSource[]` → SwitchListItem[]
// and hands them to <SwitchList />, so a row factory composes more cleanly than
// a wrapper component (no extra nesting, the leading icon is just a node).
//
// leading = <SourceIcon sourceType={source.internalName} size={16} />,
// label   = source.displayName,
// id      = source.uniqueKey,
// isEnabled / onToggle wired by the caller (useSourcePreferences).
// ---------------------------------------------------------------------------

export function toSourceItem(
  source: MobileSource,
  isEnabled: boolean,
  onToggle: () => void
): SwitchListItem {
  return {
    id: source.uniqueKey,
    label: source.displayName,
    leading: <SourceIcon sourceType={source.internalName} size={16} />,
    isEnabled,
    onToggle,
  };
}
