import { Image, type ImageProps } from "expo-image";
import { useMemo } from "react";
import { View } from "react-native";

import { getBaseUrl } from "@/api/config";
import { useAuthToken } from "@/hooks/useAuthToken";

interface BearerImageProps {
  // Bare API path, e.g. "/chat/file/123" or "/persona/1/avatar".
  path: string;
  size: number;
  radius?: number;
  contentFit?: ImageProps["contentFit"];
}

// Auth'd image via expo-image. cachePolicy="none" because the URL isn't auth-keyed — a shared
// cache could leak one account's image to the next after an instance switch. Neutral placeholder
// until the bearer resolves. Shared by AttachmentImage + AgentImage.
export function BearerImage({
  path,
  size,
  radius = size / 2,
  contentFit = "cover",
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
      contentFit={contentFit}
      cachePolicy="none"
    />
  );
}
