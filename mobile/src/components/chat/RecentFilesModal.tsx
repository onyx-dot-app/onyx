import { ScrollView, View } from "react-native";

import { Modal, Text } from "@/components/opal";
import type { ProjectFile } from "@/lib/types";
import { RecentFileRow } from "./RecentFileRow";

// Simplified mirror of web UserFilesModal — pick-only (delete/view/search are follow-ups).
interface RecentFilesModalProps {
  visible: boolean;
  onClose: () => void;
  files: ProjectFile[];
  attachedFileIds: string[];
  onToggle: (file: ProjectFile) => void;
}

export function RecentFilesModal({
  visible,
  onClose,
  files,
  attachedFileIds,
  onToggle,
}: RecentFilesModalProps) {
  const attached = new Set(attachedFileIds);
  return (
    <Modal visible={visible} onClose={onClose} title="Recent Files">
      {files.length === 0 ? (
        <Text font="secondary-body" color="text-03">
          No recent files.
        </Text>
      ) : (
        <ScrollView
          style={{ maxHeight: 360 }}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
        >
          <View>
            {files.map((file) => (
              <RecentFileRow
                key={file.id}
                file={file}
                attached={attached.has(file.file_id)}
                onToggle={onToggle}
              />
            ))}
          </View>
        </ScrollView>
      )}
    </Modal>
  );
}
