import { Pressable } from "react-native";

import { Text } from "@/components/opal";
import { SvgX } from "@/components/icons/SvgX";
import type { ToolSnapshot } from "@/lib/types/tools";

// ---------------------------------------------------------------------------
// ForcedToolChip — toolbar indicator for the tool forced for the next message.
//
// Web parity: a pressable pill showing the forced tool's display_name; tapping
// it clears the forced tool. Pill background `bg-action-link-01` (fixed → static
// class); text + ✕ glyph use `action-link-05` (dynamic colour → `Text color` /
// `useToken`, never a `text-*` className per the codebase convention).
// ---------------------------------------------------------------------------

interface ForcedToolChipProps {
  /** The tool currently forced for the next message. */
  tool: ToolSnapshot;
  /** Called when the chip is tapped (clears the forced tool). */
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
