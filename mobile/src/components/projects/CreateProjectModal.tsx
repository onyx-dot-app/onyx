import { useState } from "react";
import { View } from "react-native";
import { router } from "expo-router";

import { Button, Modal, Text } from "@/components/opal";
import { useCreateProject } from "@/query/projects";
import { useStartProjectChat } from "@/chat/useStartProjectChat";
import { ProjectModalTextInput } from "./ProjectModalTextInput";

// Native mirror of web `CreateProjectModal`: a controlled opal Modal with a single
// "Project Name" field that creates the project and navigates to its detail screen.

interface CreateProjectModalProps {
  visible: boolean;
  onClose: () => void;
}

export function CreateProjectModal({ visible, onClose }: CreateProjectModalProps) {
  const [name, setName] = useState("");
  const createProject = useCreateProject();
  const startProjectChat = useStartProjectChat();

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
          <ProjectModalTextInput
            value={name}
            onChangeText={setName}
            placeholder="What are you working on?"
            autoFocus
            returnKeyType="done"
            onSubmitEditing={handleSubmit}
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
