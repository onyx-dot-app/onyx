import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { PluginPublishingPolicy } from "@/lib/settings/types";
import { Permission } from "@/lib/types";

export type PublishAction = "publish" | "review" | "off";

/** What publishing a skill does for the current user. */
export function usePublishAction(): PublishAction {
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_PLUGINS);
  const { plugin_publishing: policy } = useSettings();
  if (isGlobalHolder) return "publish";
  if (policy === PluginPublishingPolicy.REQUIRES_REVIEW) return "review";
  if (policy === PluginPublishingPolicy.OFF) return "off";
  return "publish";
}
