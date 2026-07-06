import { useLocalSearchParams } from "expo-router";

import { ProjectView } from "@/components/chat/ProjectView";

export default function ProjectScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  // A malformed route (e.g. /projects/abc) → null, so the chat controller never
  // gets NaN and silently creates an unscoped chat.
  const parsed = Number(id);
  const projectId = Number.isFinite(parsed) ? parsed : null;
  return <ProjectView projectId={projectId} />;
}
