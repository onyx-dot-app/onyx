import { Stack } from "expo-router";

// Chat tab is a SINGLE screen (index). It renders whichever session is current —
// new draft or one opened from Recents — so there is no separate [sessionId] route;
// the screen loads the selected session's history in place.
export default function ChatLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
