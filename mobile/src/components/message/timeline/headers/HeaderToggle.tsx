// Right-side fold/expand control shared by timeline headers (replaces web's Opal Button).

import { Pressable } from "react-native";

import { Text } from "@/components/opal";
import { SvgFold, SvgExpand } from "@/components/icons";

interface HeaderToggleProps {
  isExpanded: boolean;
  onToggle: () => void;
  label?: string;
}

export function HeaderToggle({ isExpanded, onToggle, label }: HeaderToggleProps) {
  const Icon = isExpanded ? SvgFold : SvgExpand;
  return (
    <Pressable
      onPress={onToggle}
      hitSlop={8}
      accessibilityRole="button"
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        paddingHorizontal: 6,
        paddingVertical: 4,
      }}
    >
      {label ? (
        <Text font="main-ui-action" color="text-03">
          {label}
        </Text>
      ) : null}
      <Icon size={16} color="text-03" />
    </Pressable>
  );
}

export default HeaderToggle;
