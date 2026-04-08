"use client";

import { Fragment } from "react";
import useSWR from "swr";
import { ContentAction } from "@opal/layouts";
import {
  SvgSettings,
  SvgPlug,
  SvgActions,
  SvgUsers,
  SvgUserKey,
  SvgSlack,
  SvgPlusCircle,
  SvgUserManage,
  SvgBarChart,
  SvgHistory,
  SvgKey,
  SvgShield,
  SvgCpu,
  SvgFiles,
  SvgCreateAgent,
  SvgManageAgent,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import Card from "@/refresh-components/cards/Card";
import Switch from "@/refresh-components/inputs/Switch";
import Separator from "@/refresh-components/Separator";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { PermissionRegistryEntry } from "@/refresh-pages/admin/GroupsPage/interfaces";

// ---------------------------------------------------------------------------
// Icon mapping — the only permission metadata maintained in the frontend.
// The `id` keys must match the backend PERMISSION_REGISTRY entries.
// ---------------------------------------------------------------------------

const ICON_MAP: Record<string, IconFunctionComponent> = {
  manage_llms: SvgCpu,
  manage_connectors_and_document_sets: SvgFiles,
  manage_actions: SvgActions,
  manage_groups: SvgUsers,
  manage_service_accounts: SvgUserKey,
  manage_slack_discord_bots: SvgSlack,
  create_agents: SvgCreateAgent,
  manage_agents: SvgManageAgent,
  view_agent_analytics: SvgBarChart,
  view_query_history: SvgHistory,
  create_user_access_token: SvgKey,
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface GroupPermissionsSectionProps {
  enabledPermissions: Set<string>;
  onPermissionsChange: (permissions: Set<string>) => void;
}

function GroupPermissionsSection({
  enabledPermissions,
  onPermissionsChange,
}: GroupPermissionsSectionProps) {
  const { data: registry, isLoading } = useSWR<PermissionRegistryEntry[]>(
    SWR_KEYS.permissionRegistry,
    errorHandlingFetcher
  );

  function isRowEnabled(entry: PermissionRegistryEntry): boolean {
    return entry.permissions.every((p) => enabledPermissions.has(p));
  }

  function handleToggle(entry: PermissionRegistryEntry, checked: boolean) {
    const next = new Set(enabledPermissions);
    for (const perm of entry.permissions) {
      if (checked) {
        next.add(perm);
      } else {
        next.delete(perm);
      }
    }
    onPermissionsChange(next);
  }

  return (
    <SimpleCollapsible>
      <SimpleCollapsible.Header
        title="Group Permissions"
        description="Set access and permissions for members of this group."
      />
      <SimpleCollapsible.Content>
        {isLoading || !registry ? (
          <SimpleLoader />
        ) : (
          <Card>
            {registry.map((entry, index) => {
              const prevGroup =
                index > 0 ? registry[index - 1]!.group : entry.group;
              const icon = ICON_MAP[entry.id] ?? SvgShield;
              return (
                <Fragment key={entry.id}>
                  {index > 0 && entry.group !== prevGroup && (
                    <Separator noPadding />
                  )}
                  <ContentAction
                    icon={icon}
                    title={entry.display_name}
                    description={entry.description}
                    sizePreset="main-ui"
                    variant="section"
                    paddingVariant="md"
                    rightChildren={
                      <Switch
                        checked={isRowEnabled(entry)}
                        onCheckedChange={(checked) =>
                          handleToggle(entry, checked)
                        }
                      />
                    }
                  />
                </Fragment>
              );
            })}
          </Card>
        )}
      </SimpleCollapsible.Content>
    </SimpleCollapsible>
  );
}

export default GroupPermissionsSection;
