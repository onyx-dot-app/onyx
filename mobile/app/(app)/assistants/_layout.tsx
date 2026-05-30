import { Stack } from "expo-router";

// Assistants tab owns a Stack so [assistantId] pushes over the list.
export default function AssistantsLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
