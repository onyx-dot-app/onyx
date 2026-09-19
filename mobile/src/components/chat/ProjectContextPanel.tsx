import { View } from "react-native";
import { router } from "expo-router";

import { Content } from "@/components/ui/content";
import { Icon } from "@/components/ui/icon";
import { LineItemButton } from "@/components/ui/line-item-button";
import { Separator } from "@/components/ui/separator";
import { Text } from "@/components/ui/text";
import SvgChevronRight from "@/icons/chevron-right";
import SvgFolder from "@/icons/folder";
import type { ProjectDetails } from "@/chat/contracts/projects";

interface ProjectContextPanelProps {
  projectId: number | null;
  details?: ProjectDetails;
  isLoading: boolean;
}

// File management lives on the dedicated /sources/[id] screen, not here.
export function ProjectContextPanel({
  projectId,
  details,
}: ProjectContextPanelProps) {
  const project = details?.project;
  const instructions = project?.instructions?.trim();
  const fileCount = details?.files?.length ?? 0;

  return (
    <View className="gap-24">
      <Content icon={SvgFolder} title={project?.name ?? "Loading project…"} />

      <Separator />

      <Content
        sizePreset="main-ui"
        variant="section"
        title="Instructions"
        description={instructions || "No instructions for this project."}
        descriptionMaxLines={4}
      />

      <LineItemButton
        icon={SvgFolder}
        title="View sources"
        sizePreset="main-ui"
        variant="section"
        center
        disabled={projectId == null}
        onPress={() =>
          projectId != null &&
          router.navigate({
            pathname: "/sources/[id]",
            params: { id: String(projectId) },
          })
        }
        rightChildren={
          <View className="flex-row items-center gap-4">
            <Text font="secondary-body" color="text-03">
              {fileCount} {fileCount === 1 ? "file" : "files"}
            </Text>
            <Icon as={SvgChevronRight} size={16} className="text-text-03" />
          </View>
        }
      />
    </View>
  );
}
