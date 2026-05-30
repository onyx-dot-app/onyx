import { Stack } from "expo-router";

// Chat tab owns a Stack so [sessionId] pushes over the session list rather
// than swapping the whole tab.
export default function ChatLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
