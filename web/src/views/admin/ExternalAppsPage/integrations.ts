import { MCPServer } from "@/lib/tools/types";
import { updateMCPServer } from "@/lib/tools/svc";
import { getActionIcon } from "@/lib/tools/utils";
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

/** Translated fact and warning copy, supplied by the rendering component
 * because this module cannot call translation hooks. */
export interface IntegrationLabels {
  providedByOnyx: string;
  noCredentials: string;
  orgCredentialsSet: string;
  perUserCredentials: string;
  noCustomSkills: string;
  invalidSkill: string;
  providerUnavailable: string;
  upstreamPatternCount: (count: number) => string;
  actionCount: (count: number) => string;
  customSkillCount: (count: number) => string;
  toolCount: (count: number) => string;
}

/** The auth template's placeholders name the credentials the proxy injects;
 * whoever must supply the org-uncovered ones is the fact. */
function customCredentialFact(
  app: ExternalAppAdminResponse,
  labels: IntegrationLabels
): string {
  const keys = app.credential_placeholder_keys;
  if (keys.length === 0) return labels.noCredentials;
  return keys.every((key) => Object.hasOwn(app.organization_credentials, key))
    ? labels.orgCredentialsSet
    : labels.perUserCredentials;
}

function externalAppFacts(
  app: ExternalAppAdminResponse,
  labels: IntegrationLabels
): string[] {
  const facts: string[] = [];
  if (app.is_onyx_managed) facts.push(labels.providedByOnyx);
  if (app.app_type === "CUSTOM") {
    facts.push(labels.upstreamPatternCount(app.upstream_url_patterns.length));
    facts.push(customCredentialFact(app, labels));
  }
  if (app.actions.length > 0) {
    facts.push(labels.actionCount(app.actions.length));
  }
  facts.push(
    app.associated_skills.length > 0
      ? labels.customSkillCount(app.associated_skills.length)
      : labels.noCustomSkills
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
  { onEdit, onEditCustom, onChange }: ExternalAppHandlers,
  labels: IntegrationLabels
): ConfiguredIntegration {
  const isCustom = app.app_type === "CUSTOM";
  const orphaned = !isCustom && descriptor === undefined;
  const warnings: string[] = [];
  if (app.associated_skills.some((skill) => skill.is_valid === false)) {
    warnings.push(labels.invalidSkill);
  }
  if (orphaned) warnings.push(labels.providerUnavailable);
  return {
    key: `app-${app.id}`,
    isCustom,
    logo: getAppTypeLogo(app.app_type),
    name: app.name,
    facts: externalAppFacts(app, labels),
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
  { onEdit, onChange }: McpServerHandlers,
  labels: IntegrationLabels
): ConfiguredIntegration {
  const enabled = server.available_in_craft ?? false;
  return {
    key: `mcp-${server.id}`,
    isCustom: false,
    logo: getActionIcon(server.server_url, server.name),
    name: server.name,
    facts: [labels.toolCount(server.tool_count)],
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
