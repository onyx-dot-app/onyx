import { MCPServer } from "@/lib/tools/interfaces";
import { updateMCPServer } from "@/lib/tools/mcpService";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import {
  BuiltInExternalAppDescriptor,
  ExternalAppAdminResponse,
  getAppTypeLogo,
} from "@/app/craft/v1/apps/registry";
import {
  deleteExternalApp,
  updateExternalApp,
} from "@/app/craft/services/externalAppsService";
import { ConfiguredIntegration } from "@/views/admin/ExternalAppsPage/interfaces";

function countLabel(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** The auth template's placeholders name the credentials the proxy injects;
 * whoever must supply the org-uncovered ones is the fact. */
function customCredentialFact(app: ExternalAppAdminResponse): string {
  const keys = app.credential_placeholder_keys;
  if (keys.length === 0) return "no credentials";
  return keys.every((key) => Object.hasOwn(app.organization_credentials, key))
    ? "org credentials set"
    : "per-user credentials";
}

function externalAppFacts(app: ExternalAppAdminResponse): string[] {
  const facts: string[] = [];
  if (app.is_onyx_managed) facts.push("provided by Onyx");
  if (app.app_type === "CUSTOM") {
    facts.push(
      countLabel(app.upstream_url_patterns.length, "upstream pattern")
    );
    facts.push(customCredentialFact(app));
  }
  if (app.actions.length > 0) {
    facts.push(countLabel(app.actions.length, "action"));
  }
  facts.push(
    app.associated_skills.length > 0
      ? countLabel(app.associated_skills.length, "custom skill")
      : "no custom skills"
  );
  return facts;
}

interface ExternalAppHandlers {
  /** Edit a built-in provider instance (driven by its descriptor). */
  onEdit: (descriptor: BuiltInExternalAppDescriptor) => void;
  /** Edit a custom app (no descriptor — config is on the row itself). */
  onEditCustom: (app: ExternalAppAdminResponse) => void;
  onChange: () => Promise<void>;
}

export function externalAppToIntegration(
  app: ExternalAppAdminResponse,
  /** Undefined when the app's app_type no longer has a backend descriptor. */
  descriptor: BuiltInExternalAppDescriptor | undefined,
  { onEdit, onEditCustom, onChange }: ExternalAppHandlers
): ConfiguredIntegration {
  const isCustom = app.app_type === "CUSTOM";
  const orphaned = !isCustom && descriptor === undefined;
  const warnings: string[] = [];
  if (app.associated_skills.some((skill) => skill.is_valid === false)) {
    warnings.push("invalid skill");
  }
  if (orphaned) warnings.push("provider unavailable");
  return {
    key: `app-${app.id}`,
    isCustom,
    logo: getAppTypeLogo(app.app_type),
    name: app.name,
    facts: externalAppFacts(app),
    warnings,
    enabled: app.enabled,
    toggleEnabled: async () => {
      await updateExternalApp(app.id, { enabled: !app.enabled });
      await onChange();
    },
    // Edit only works for custom apps and built-ins whose descriptor still
    // exists; orphan app_types can only be disabled/deleted.
    edit: isCustom
      ? () => onEditCustom(app)
      : descriptor
        ? () => onEdit(descriptor)
        : null,
    // Onyx-managed built-ins are provisioned by Onyx.
    remove: app.is_onyx_managed
      ? null
      : {
          retainedCustomSkillCount: app.associated_skills.length,
          run: async () => {
            await deleteExternalApp(app.id);
            await onChange();
          },
        },
  };
}

interface McpServerHandlers {
  onEdit: () => void;
  onChange: () => Promise<void>;
}

export function mcpServerToIntegration(
  server: MCPServer,
  { onEdit, onChange }: McpServerHandlers
): ConfiguredIntegration {
  const enabled = server.available_in_craft ?? false;
  return {
    key: `mcp-${server.id}`,
    isCustom: false,
    logo: getActionIcon(server.server_url, server.name),
    name: server.name,
    facts: [countLabel(server.tool_count, "tool")],
    warnings: [],
    enabled,
    toggleEnabled: async () => {
      await updateMCPServer(server.id, { available_in_craft: !enabled });
      await onChange();
    },
    edit: onEdit,
    remove: null,
  };
}
