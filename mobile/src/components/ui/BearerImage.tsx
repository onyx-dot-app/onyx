import { Image } from "expo-image";
import { useMemo } from "react";
import { View } from "react-native";

import { getBaseUrl } from "@/api/config";
import { useAuthToken } from "@/hooks/useAuthToken";

interface BearerImageProps {
  // Bare API path, e.g. "/chat/file/123" or "/persona/1/avatar".
  path: string;
  size: number;
  radius?: number;
}

// Auth'd image via expo-image. cachePolicy="none" because the URL isn't auth-keyed — a shared
// cache could leak one account's image to the next after an instance switch. Neutral placeholder
// until the bearer resolves. Shared by AttachmentImage + AgentImage.
export function BearerImage({
  path,
  size,
  radius = size / 2,
}: BearerImageProps) {
  const token = useAuthToken();
  const baseUrl = getBaseUrl();
  const dimension = useMemo(
    () => ({ width: size, height: size, borderRadius: radius }),
    [size, radius],
  );
  // Stable source ref (cachePolicy="none" means a fresh object would trigger a re-fetch).
  // baseUrl is a dep so the source changes at an instance switch, not just on path/token.
  const source = useMemo(
    () =>
      token
        ? {
            uri: `${baseUrl}${path}`,
            headers: { Authorization: `Bearer ${token}` },
          }
        : null,
    [baseUrl, path, token],
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
