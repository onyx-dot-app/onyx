import { Pressable } from "react-native";

import { Text } from "@/components/opal";
import { SvgX } from "@/components/icons/SvgX";
import type { ToolSnapshot } from "@/lib/types/tools";

// Pill for the tool forced for the next message; tapping clears it.
interface ForcedToolChipProps {
  tool: ToolSnapshot;
  onClear: () => void;
}

export function ForcedToolChip({ tool, onClear }: ForcedToolChipProps) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Forced: ${tool.display_name}. Tap to clear.`}
      hitSlop={6}
      onPress={onClear}
      className="h-8 flex-row items-center gap-1 rounded-[8px] bg-action-link-01 px-2"
    >
      <Text font="secondary-action" color="action-link-05" numberOfLines={1}>
        {tool.display_name}
      </Text>
      <SvgX size={12} color="action-link-05" />
    </Pressable>
  );
}
