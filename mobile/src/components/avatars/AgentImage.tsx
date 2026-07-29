import { BearerImage } from "@/components/ui/BearerImage";

interface AgentImageProps {
  agentId: number;
  size: number;
}

// Uploaded avatar (GET /persona/{id}/avatar) as a circle via the shared BearerImage primitive
// (BearerImage's default radius = size / 2).
export function AgentImage({ agentId, size }: AgentImageProps) {
  return <BearerImage path={`/persona/${agentId}/avatar`} size={size} />;
}
