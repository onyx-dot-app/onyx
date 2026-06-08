import { View } from "react-native";

import { AttachmentTile, type AttachmentTileModel } from "./AttachmentTile";

// Native mirror of web's files wrapper; switches images to compact size when >1 file.
interface AttachmentTrayProps {
  models: AttachmentTileModel[];
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
