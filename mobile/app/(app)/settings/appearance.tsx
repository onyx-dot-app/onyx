import { Text, View } from "react-native";

// Placeholder. Wires to the theme_preference (light/dark/system) control from
// doc 03 later.
export default function Appearance() {
  return (
    <View className="flex-1 items-center justify-center bg-background-neutral-00">
      <Text className="text-text-05 font-semibold">Appearance</Text>
    </View>
  );
}
