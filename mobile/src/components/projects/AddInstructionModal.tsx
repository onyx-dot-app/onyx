import { useState } from "react";
import { TextInput, View } from "react-native";

import { Button, Modal, Text } from "@/components/opal";
import { typography } from "@/theme/generated/typography";
import { useToken } from "@/theme/ThemeProvider";
import { useUpsertProjectInstructions } from "@/query/projects";

// Native mirror of web `AddInstructionModal`. Controlled opal Modal with a
// multiline instructions field, seeded from the project's current instructions.
// Same copy + colors as web.

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
  const placeholderColor = useToken("text-03");
  const typedColor = useToken("text-05");

  // Re-seed the field each time the sheet OPENS so it reflects the latest saved
  // value. Tracking the previous `visible` and setting state during render (not
  // in an effect) is React's recommended "reset state on prop change" pattern.
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
      // Keep open on failure so the user doesn't lose their text.
    }
  }

  return (
    <Modal visible={visible} onClose={onClose} title="Set Project Instructions">
      <View className="gap-4">
        <Text font="secondary-body" color="text-03">
          Specify the behaviors or tone for the chat sessions in this project.
        </Text>

        <TextInput
          value={text}
          onChangeText={setText}
          placeholder="My goal with is to... be sure to... in your responses."
          placeholderTextColor={placeholderColor}
          autoFocus
          multiline
          textAlignVertical="top"
          className="rounded-[8px] border border-border-02 bg-background-neutral-00 px-3 py-2"
          style={[
            typography["main-ui-body"],
            { color: typedColor, minHeight: 120, maxHeight: 240 },
          ]}
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
