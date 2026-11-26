import type { MemberIntegration } from "@/lib/integrations/types";

/** True when a chat uses the integration: a Required one is always on, and
 * any other one follows the chat's switch. */
export function isIntegrationOnInChat(
  integration: MemberIntegration,
  isIntegrationEnabled: (integrationId: number) => boolean
): boolean {
  return (
    integration.access.installation_policy === "REQUIRED" ||
    isIntegrationEnabled(integration.id)
  );
}
