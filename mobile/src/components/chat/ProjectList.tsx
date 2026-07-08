import { View } from "react-native";

import { Text } from "@/components/ui/text";
// Leaf import (not the barrel) avoids the overlay's reanimated dep, keeping this
// jest-testable.
import { SidebarTab } from "@/components/sidebar/SidebarTab";
import SvgFolder from "@/icons/folder";
import type { Project } from "@/chat/contracts/projects";

interface ProjectListProps {
  projects: Project[];
  currentProjectId?: number | null;
  isLoading?: boolean;
  onSelect: (projectId: number) => void;
}

// Sidebar "Projects" list; read-only in PR 6 (no create/rename/delete).
export function ProjectList({
  projects,
  currentProjectId,
  isLoading = false,
  onSelect,
}: ProjectListProps) {
  if (!isLoading && projects.length === 0) {
    return (
      <View className="px-2 py-2">
        <Text font="secondary-body" color="text-03">
          No projects yet.
        </Text>
      </View>
    );
  }

  return (
    <>
      {projects.map((project) => (
        <SidebarTab
          key={project.id}
          icon={SvgFolder}
          selected={project.id === currentProjectId}
          onPress={() => onSelect(project.id)}
        >
          {project.name}
        </SidebarTab>
      ))}
    </>
  );
}
