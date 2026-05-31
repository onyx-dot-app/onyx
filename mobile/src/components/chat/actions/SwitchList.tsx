import { type ReactNode } from "react";
import { View } from "react-native";

import { Switch, Text } from "@/components/opal";

// ---------------------------------------------------------------------------
// SwitchList — a generic list of toggle rows (web parity `SwitchList`).
//
// Each row: optional leading node + label (`Text`) + opal `Switch`. Used by the
// sources sub-view of the actions popover, but kept fully generic so any
// enable/disable list can reuse it.
// ---------------------------------------------------------------------------

export interface SwitchListItem {
  /** Stable key for the row. */
  id: string;
  /** Row label text. */
  label: string;
  /** Optional leading node (e.g. a source icon). */
  leading?: ReactNode;
  /** Whether the row's switch is on. */
  isEnabled: boolean;
  /** Toggle handler for the switch. */
  onToggle: () => void;
}

interface SwitchListProps {
  items: SwitchListItem[];
}

export function SwitchList({ items }: SwitchListProps) {
  return (
    <View>
      {items.map((item) => (
        <View
          key={item.id}
          className="flex-row items-center justify-between gap-2 rounded-[8px] px-3 py-2"
        >
          <View className="flex-1 flex-row items-center gap-2">
            {item.leading}
            <Text
              font="main-ui-body"
              color="text-04"
              numberOfLines={1}
              style={{ flex: 1 }}
            >
              {item.label}
            </Text>
          </View>
          <Switch
            value={item.isEnabled}
            onValueChange={item.onToggle}
            accessibilityLabel={`Toggle ${item.label}`}
          />
        </View>
      ))}
    </View>
  );
}

export default SwitchList;
