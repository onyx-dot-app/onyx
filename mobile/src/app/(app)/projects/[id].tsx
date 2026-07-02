import { useLocalSearchParams } from "expo-router";

import { ProjectView } from "@/components/chat/ProjectView";

export default function ProjectScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <ProjectView projectId={Number(id)} />;
}
