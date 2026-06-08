import { Text, View } from "react-native";

// Shared placeholder body for not-yet-built screens: a centered label on the
// neutral background. Real UI lands in docs 05/06.
export function PlaceholderScreen({ label }: { label: string }) {
  return (
    <View className="flex-1 items-center justify-center bg-background-neutral-00">
      <Text className="text-text-05 font-semibold">{label}</Text>
    </View>
  );
}
