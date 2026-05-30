import { Text, View } from "react-native";

// Placeholder. Presented modally (native sheet). Real new-chat flow lands in
// docs 05/06.
export default function NewChat() {
  return (
    <View className="flex-1 items-center justify-center bg-background-neutral-00">
      <Text className="text-text-05 font-semibold">New chat</Text>
    </View>
  );
}
