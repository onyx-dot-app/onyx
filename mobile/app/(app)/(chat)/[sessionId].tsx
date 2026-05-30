import { useLocalSearchParams } from "expo-router";
import { Text, View } from "react-native";

// Placeholder. The streaming chat UI (FlashList + streaming hook) lands in
// docs 05/06.
export default function ChatSession() {
  const { sessionId } = useLocalSearchParams<{ sessionId: string }>();

  return (
    <View className="flex-1 items-center justify-center bg-background-neutral-00">
      <Text className="text-text-05 font-semibold">Chat session {sessionId}</Text>
    </View>
  );
}
