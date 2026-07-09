import { Image } from "expo-image";
import { useMemo } from "react";
import { View } from "react-native";

import { getBaseUrl } from "@/api/config";
import { useAuthToken } from "@/hooks/useAuthToken";

interface AttachmentImageProps {
  fileId: string;
  size: number;
  radius?: number;
}

// Auth'd image preview (GET /chat/file/{file_id}) for an attachment thumbnail. Mirrors
// AgentImage: caching is disabled because the URL isn't keyed by auth, so a shared cache
// could serve one account's file to the next after a switch. Neutral placeholder until the
// bearer resolves.
export function AttachmentImage({
  fileId,
  size,
  radius = 8,
}: AttachmentImageProps) {
  const token = useAuthToken();
  const dimension = useMemo(
    () => ({ width: size, height: size, borderRadius: radius }),
    [size, radius],
  );
  // Stable source ref (cachePolicy="none" means a fresh object would trigger a re-fetch).
  const source = useMemo(
    () =>
      token
        ? {
            uri: `${getBaseUrl()}/chat/file/${fileId}`,
            headers: { Authorization: `Bearer ${token}` },
          }
        : null,
    [fileId, token],
  );

  if (!source) {
    return <View style={dimension} className="bg-background-tint-01" />;
  }

  return (
    <Image
      source={source}
      style={dimension}
      contentFit="cover"
      cachePolicy="none"
    />
  );
}
