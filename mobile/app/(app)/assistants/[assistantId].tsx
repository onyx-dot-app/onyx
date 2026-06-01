import { useLocalSearchParams } from "expo-router";

import { PlaceholderScreen } from "@/components/PlaceholderScreen";

// Placeholder. Real assistant detail lands in docs 05/06.
export default function AssistantDetail() {
  const { assistantId } = useLocalSearchParams<{ assistantId: string }>();

  return <PlaceholderScreen label={`Assistant ${assistantId}`} />;
}
