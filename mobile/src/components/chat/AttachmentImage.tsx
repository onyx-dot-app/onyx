import { BearerImage } from "@/components/ui/BearerImage";

interface AttachmentImageProps {
  fileId: string;
  size: number;
  radius?: number;
}

// Auth'd attachment thumbnail (GET /chat/file/{file_id}) — a rounded square via the shared
// BearerImage primitive.
export function AttachmentImage({
  fileId,
  size,
  radius = 8,
}: AttachmentImageProps) {
  return (
    <BearerImage path={`/chat/file/${fileId}`} size={size} radius={radius} />
  );
}
