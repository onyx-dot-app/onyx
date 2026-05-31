import { View } from "react-native";

import { AttachmentTile, type AttachmentTileModel } from "./AttachmentTile";

// AttachmentTray — native mirror of web's files wrapper
// (`flex flex-wrap gap-1 p-1`). Lays out attachment tiles in a wrapping row and
// switches images to the 44×44 compact size when more than one file is attached
// (web `shouldCompactImages = currentMessageFiles.length > 1`). Removable in the
// composer; read-only (no `onRemove`) in sent message bubbles.

interface AttachmentTrayProps {
  models: AttachmentTileModel[];
  /** When provided, each tile shows a remove affordance. */
  onRemove?: (id: string) => void;
}

export function AttachmentTray({ models, onRemove }: AttachmentTrayProps) {
  if (models.length === 0) return null;
  const compact = models.length > 1;
  return (
    <View className="flex-row flex-wrap gap-1 p-1">
      {models.map((model) => (
        <AttachmentTile
          key={model.id}
          model={model}
          compact={compact}
          onRemove={onRemove}
        />
      ))}
    </View>
  );
}
