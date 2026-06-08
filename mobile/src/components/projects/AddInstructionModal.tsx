import { useState } from "react";
import { View } from "react-native";

import { Button, Modal, Text } from "@/components/opal";
import { useUpsertProjectInstructions } from "@/query/projects";
import { ProjectModalTextInput } from "./ProjectModalTextInput";

// Native mirror of web AddInstructionModal.

interface AddInstructionModalProps {
  visible: boolean;
  onClose: () => void;
  projectId: number;
  initialInstructions: string | null;
}

export function AddInstructionModal({
  visible,
  onClose,
  projectId,
  initialInstructions,
}: AddInstructionModalProps) {
  const [text, setText] = useState(initialInstructions ?? "");
  const upsert = useUpsertProjectInstructions(projectId);

  // Re-seed on open via React's "reset state on prop change" render pattern (not an effect).
  const [wasVisible, setWasVisible] = useState(visible);
  if (visible !== wasVisible) {
    setWasVisible(visible);
    if (visible) setText(initialInstructions ?? "");
  }

  async function handleSave() {
    try {
      await upsert.mutateAsync(text.trim());
      onClose();
    } catch {
      // Keep open so the user doesn't lose their text.
    }
  }

  return (
    <Modal visible={visible} onClose={onClose} title="Set Project Instructions">
      <View className="gap-4">
        <Text font="secondary-body" color="text-03">
          Specify the behaviors or tone for the chat sessions in this project.
        </Text>

        <ProjectModalTextInput
          value={text}
          onChangeText={setText}
          placeholder="My goal with is to... be sure to... in your responses."
          autoFocus
          multiline
          textAlignVertical="top"
          style={{ minHeight: 120, maxHeight: 240 }}
        />

        <View className="flex-row justify-end gap-2">
          <Button variant="default" prominence="secondary" onPress={onClose}>
            Cancel
          </Button>
          <Button
            variant="default"
            prominence="primary"
            disabled={upsert.isPending}
            onPress={handleSave}
          >
            Save Instructions
          </Button>
        </View>
      </View>
    </Modal>
  );
}
