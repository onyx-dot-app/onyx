import { Stack } from "expo-router";

// Modals group. The root Stack already presents the whole (modals) group with
// presentation: "modal" (native sheet); this inner Stack just groups the modal
// routes. Native confirm dialogs use a bottom-sheet primitive (see doc 05),
// not this group.
export default function ModalsLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
