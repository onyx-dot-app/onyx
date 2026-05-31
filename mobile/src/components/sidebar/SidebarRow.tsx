import { Pressable } from "react-native";

import { Text } from "@/components/opal";

// One sidebar chat row — mirrors the web ChatButton/SidebarTab. Spacing via NativeWind
// classNames (inline horizontal style is unreliable under NativeWind here):
//   mx-2 → 8px inset so the highlight sits in from the drawer edge (web `body px-2`)
//   px-2 → text lands at 16px total
//   h-10 → 40px row, justify-center vertical
//   selected → bg-background-tint-00 + text-04; pressed → bg-background-tint-03 (active:)
export function SidebarRow({
  label,
  selected = false,
  onPress,
}: {
  label: string;
  selected?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      className={`mx-2 h-10 justify-center rounded-[8px] px-2 active:bg-background-tint-03 ${
        selected ? "bg-background-tint-00" : ""
      }`}
    >
      <Text
        font="main-ui-body"
        color={selected ? "text-04" : "text-03"}
        numberOfLines={1}
      >
        {label}
      </Text>
    </Pressable>
  );
}
