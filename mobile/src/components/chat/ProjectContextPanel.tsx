import { ActivityIndicator, View } from "react-native";

import { Content } from "@/components/ui/content";
import { Text } from "@/components/ui/text";
import { Separator } from "@/components/ui/separator";
import { FileCard } from "@/components/chat/FileCard";
import SvgFolder from "@/icons/folder";
import type { ProjectDetails } from "@/chat/contracts/projects";

interface ProjectContextPanelProps {
  details?: ProjectDetails;
  isLoading: boolean;
}

// Read-only (mirrors web's ProjectContextPanel); the Set Instructions / Add
// Files actions are PR 7.
export function ProjectContextPanel({
  details,
  isLoading,
}: ProjectContextPanelProps) {
  const project = details?.project;
  const files = details?.files ?? [];
  const instructions = project?.instructions?.trim();
  const loadingDetails = isLoading && !details;

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

      <View className="gap-8">
        <Content
          sizePreset="main-ui"
          variant="section"
          title="Files"
          description="Chats in this project can access these files."
        />

        {loadingDetails ? (
          <ActivityIndicator size="small" />
        ) : files.length === 0 ? (
          <View className="justify-center rounded-12 border border-dashed border-border-01 px-12 py-12">
            <Text font="secondary-body" color="text-02">
              No files in this project yet.
            </Text>
          </View>
        ) : (
          <View className="gap-8">
            {files.map((file) => (
              <FileCard key={file.id} file={file} />
            ))}
          </View>
        )}
      </View>
    </View>
  );
}
