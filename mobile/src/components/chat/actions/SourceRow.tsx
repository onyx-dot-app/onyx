import { SourceIcon } from "@/components/message/sources/SourceIcon";
import type { MobileSource } from "@/lib/sources/sourceMetadata";
import type { SwitchListItem } from "./SwitchList";

// A row factory (not a component) so the actions popover can map MobileSource[]
// straight to SwitchListItem[] without extra nesting.
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
