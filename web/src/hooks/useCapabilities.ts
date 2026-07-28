import { useUser } from "@/providers/UserProvider";
import { hasPermission } from "@/lib/permissions";
import { Permission } from "@/lib/types";

// Coarse "may this user reach X at all" check for affordances not tied to a fetched
// resource (nav, a global "New X" button). Uses admin_capabilities, so a group manager
// is included — unlike raw effective_permissions.
export function useCapabilities(...required: Permission[]): boolean {
  const { adminCapabilities } = useUser();
  return hasPermission(adminCapabilities, ...required);
}
