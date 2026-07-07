import { Image } from "expo-image";
import { View } from "react-native";

import { getBaseUrl } from "@/api/config";
import { useAuthToken } from "@/hooks/useAuthToken";

interface AgentImageProps {
  agentId: number;
  size: number;
}

// Uploaded avatar (auth'd GET /persona/{id}/avatar) as a circle. Caching is disabled: the URL
// isn't keyed by auth, so a shared cache could serve one account's avatar to the next after a
// switch. Neutral placeholder until the bearer resolves.
export function AgentImage({ agentId, size }: AgentImageProps) {
  const token = useAuthToken();
  const dimension = { width: size, height: size, borderRadius: size / 2 };

  if (!token) {
    return <View style={dimension} className="bg-background-tint-01" />;
  }

  return (
    <Image
      source={{
        uri: `${getBaseUrl()}/persona/${agentId}/avatar`,
        headers: { Authorization: `Bearer ${token}` },
      }}
      style={dimension}
      contentFit="cover"
      cachePolicy="none"
    />
  );
}
