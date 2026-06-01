import { useState } from "react";
import { TextInput, View } from "react-native";
import { router } from "expo-router";

import { Button, Modal, Text } from "@/components/opal";
import { typography } from "@/theme/generated/typography";
import { useToken } from "@/theme/ThemeProvider";
import { useCreateProject } from "@/query/projects";
import { useStartProjectChat } from "@/chat/useStartProjectChat";

// Native mirror of web `CreateProjectModal`. A controlled opal Modal with a single
// "Project Name" field. On submit it creates the project and navigates to its
// detail screen (web: route({projectId})). Same copy + colors as web.

interface CreateProjectModalProps {
  visible: boolean;
  onClose: () => void;
}

export function CreateProjectModal({ visible, onClose }: CreateProjectModalProps) {
  const [name, setName] = useState("");
  const createProject = useCreateProject();
  const startProjectChat = useStartProjectChat();
  const placeholderColor = useToken("text-03");
  const typedColor = useToken("text-05");

  const trimmed = name.trim();
  const canSubmit = trimmed.length > 0 && !createProject.isPending;

  function close() {
    setName("");
    onClose();
  }

  async function handleSubmit() {
    if (!canSubmit) return;
    try {
      const project = await createProject.mutateAsync(trimmed);
      close();
      // Open the new project at its landing (fresh project-bound draft).
      startProjectChat(project.id);
      router.navigate(`/(app)/projects/${project.id}` as never);
    } catch {
      // Surface inline; keep the modal open so the user can retry.
    }
  }

  return (
    <Modal visible={visible} onClose={close} title="Create New Project">
      <View className="gap-4">
        <Text font="secondary-body" color="text-03">
          Use projects to organize your files and chats in one place, and add
          custom instructions for ongoing work.
        </Text>

        <View className="gap-1.5">
          <Text font="main-ui-action" color="text-04">
            Project Name
          </Text>
          <TextInput
            value={name}
            onChangeText={setName}
            placeholder="What are you working on?"
            placeholderTextColor={placeholderColor}
            autoFocus
            returnKeyType="done"
            onSubmitEditing={handleSubmit}
            className="rounded-[8px] border border-border-02 bg-background-neutral-00 px-3 py-2"
            style={[typography["main-ui-body"], { color: typedColor }]}
          />
        </View>

        <View className="flex-row justify-end gap-2">
          <Button variant="default" prominence="secondary" onPress={close}>
            Cancel
          </Button>
          <Button
            variant="default"
            prominence="primary"
            disabled={!canSubmit}
            onPress={handleSubmit}
          >
            Create Project
          </Button>
        </View>
      </View>
    </Modal>
  );
}
