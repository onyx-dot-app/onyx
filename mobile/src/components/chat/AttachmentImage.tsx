import type { ImageProps } from "expo-image";

import { BearerImage } from "@/components/ui/BearerImage";

interface AttachmentImageProps {
  fileId: string;
  size: number;
  radius?: number;
  contentFit?: ImageProps["contentFit"];
}

// Auth'd attachment thumbnail (GET /chat/file/{file_id}) — a rounded square via the shared
// BearerImage primitive.
export function AttachmentImage({
  fileId,
  size,
  radius = 8,
  contentFit,
}: AttachmentImageProps) {
  return (
    <BearerImage
      path={`/chat/file/${fileId}`}
      size={size}
      radius={radius}
      contentFit={contentFit}
    />
  );
}
