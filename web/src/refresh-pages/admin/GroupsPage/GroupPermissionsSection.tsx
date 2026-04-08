"use client";

import { Fragment } from "react";
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
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import Card from "@/refresh-components/cards/Card";
import Switch from "@/refresh-components/inputs/Switch";
import Separator from "@/refresh-components/Separator";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";

// ---------------------------------------------------------------------------
// Permission row configuration
// ---------------------------------------------------------------------------

interface PermissionRowConfig {
  permissions: string[];
  icon: IconFunctionComponent;
  title: string;
  description: string;
  group: number;
}

const PERMISSION_ROWS: PermissionRowConfig[] = [
  // Group 0 — System Configuration
  {
    permissions: ["manage:llms"],
    icon: SvgSettings,
    title: "Manage LLMs",
    description: "Add and update configurations for language models (LLMs).",
    group: 0,
  },
  {
    permissions: [
      "manage:connectors",
      "manage:document_sets",
      "add:connectors",
    ],
    icon: SvgPlug,
    title: "Manage Connectors & Document Sets",
    description: "Add and update connectors and document sets.",
    group: 0,
  },
  {
    permissions: ["manage:actions"],
    icon: SvgActions,
    title: "Manage Actions",
    description: "Add and update custom tools and MCP/OpenAPI actions.",
    group: 0,
  },
  // Group 1 — User & Access Management
  {
    permissions: ["manage:user_groups"],
    icon: SvgUsers,
    title: "Manage Groups",
    description: "Add and update user groups.",
    group: 1,
  },
  {
    permissions: ["create:service_account_api_keys"],
    icon: SvgUserKey,
    title: "Manage Service Accounts",
    description: "Add and update service accounts and their API keys.",
    group: 1,
  },
  {
    permissions: ["create:slack_discord_bots"],
    icon: SvgSlack,
    title: "Manage Slack/Discord Bots",
    description: "Add and update Onyx integrations with Slack or Discord.",
    group: 1,
  },
  // Group 2 — Agents
  {
    permissions: ["add:agents"],
    icon: SvgPlusCircle,
    title: "Create Agents",
    description: "Create and edit the user's own agents.",
    group: 2,
  },
  {
    permissions: ["manage:agents"],
    icon: SvgUserManage,
    title: "Manage Agents",
    description:
      "View and update all public and shared agents in the organization.",
    group: 2,
  },
  // Group 3 — Monitoring & Tokens
  {
    permissions: ["read:agent_analytics"],
    icon: SvgBarChart,
    title: "View Agent Analytics",
    description: "View analytics for agents the group can manage.",
    group: 3,
  },
  {
    permissions: ["read:query_history"],
    icon: SvgHistory,
    title: "View Query History",
    description: "View query history of everyone in the organization.",
    group: 3,
  },
  {
    permissions: ["create:user_api_keys"],
    icon: SvgKey,
    title: "Create User Access Token",
    description: "Add and update the user's personal access tokens.",
    group: 3,
  },
];

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
  function isRowEnabled(row: PermissionRowConfig): boolean {
    return row.permissions.every((p) => enabledPermissions.has(p));
  }

  function handleToggle(row: PermissionRowConfig, checked: boolean) {
    const next = new Set(enabledPermissions);
    for (const perm of row.permissions) {
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
        <Card>
          {PERMISSION_ROWS.map((row, index) => {
            const prevGroup =
              index > 0 ? PERMISSION_ROWS[index - 1]!.group : row.group;
            return (
              <Fragment key={row.title}>
                {index > 0 && row.group !== prevGroup && (
                  <Separator noPadding />
                )}
                <ContentAction
                  icon={row.icon}
                  title={row.title}
                  description={row.description}
                  sizePreset="main-ui"
                  variant="section"
                  paddingVariant="md"
                  rightChildren={
                    <Switch
                      checked={isRowEnabled(row)}
                      onCheckedChange={(checked) => handleToggle(row, checked)}
                    />
                  }
                />
              </Fragment>
            );
          })}
        </Card>
      </SimpleCollapsible.Content>
    </SimpleCollapsible>
  );
}

export default GroupPermissionsSection;
