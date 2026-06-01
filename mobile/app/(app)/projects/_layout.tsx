import { Stack } from "expo-router";

// Projects route group owns a Stack so [projectId] pushes over whatever invoked it.
export default function ProjectsLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
