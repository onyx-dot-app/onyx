import { useLocalSearchParams } from "expo-router";
import { Text, View } from "react-native";

// Placeholder. Real assistant detail lands in docs 05/06.
export default function AssistantDetail() {
  const { assistantId } = useLocalSearchParams<{ assistantId: string }>();

  return (
    <View className="flex-1 items-center justify-center bg-background-neutral-00">
      <Text className="text-text-05 font-semibold">Assistant {assistantId}</Text>
    </View>
  );
}
