import { useLocalSearchParams } from "expo-router";

import { PlaceholderScreen } from "@/components/PlaceholderScreen";

export default function AssistantDetail() {
  const { assistantId } = useLocalSearchParams<{ assistantId: string }>();

  return <PlaceholderScreen label={`Assistant ${assistantId}`} />;
}
