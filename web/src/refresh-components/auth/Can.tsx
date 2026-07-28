import { can, WithPermissions } from "@/lib/permissions/resource-actions";

interface CanProps {
  resource: WithPermissions | null | undefined;
  action: string;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

// Renders children only when the server authorized `action` on `resource`. The client
// reads that answer; it never recomputes policy.
export default function Can({
  resource,
  action,
  children,
  fallback = null,
}: CanProps) {
  return <>{can(resource, action) ? children : fallback}</>;
}
