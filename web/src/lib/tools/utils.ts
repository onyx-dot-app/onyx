import { SOURCE_METADATA_MAP } from "@/lib/sources";
import { MethodSpec, ToolSnapshot } from "@/lib/tools/types";
import {
  ADMIN_CONFIG_LINKS,
  CONFIGURE_MESSAGE,
  DEFAULT_TOOL_DESCRIPTION,
  OPENAPI_ADMIN_CONFIG,
  TOOL_DESCRIPTIONS,
  USER_NOT_ADMIN_MESSAGE,
} from "@/lib/tools/constants";
import type { IconProps } from "@opal/types";
import { SvgFileText, SvgServer } from "@opal/icons";

const SUPPORTED_HTTP_METHODS = new Set([
  "get",
  "post",
  "put",
  "patch",
  "delete",
  "options",
  "head",
]);

/**
 * Get an appropriate icon for an MCP server based on its URL and name.
 * Leverages the existing SOURCE_METADATA_MAP for connector icons.
 */
export function getActionIcon(
  serverUrl: string,
  serverName: string
): React.FunctionComponent<IconProps> {
  const url = serverUrl.toLowerCase();
  const name = serverName.toLowerCase();

  for (const [sourceKey, metadata] of Object.entries(SOURCE_METADATA_MAP)) {
    const keyword = sourceKey.toLowerCase();

    if (url.includes(keyword) || name.includes(keyword)) {
      const Icon = metadata.icon;
      return Icon;
    }
  }

  if (
    url.includes("postgres") ||
    url.includes("mysql") ||
    url.includes("mongodb") ||
    url.includes("redis")
  ) {
    return SvgServer;
  }
  if (url.includes("filesystem") || name.includes("file system")) {
    return SvgFileText;
  }

  return SvgServer;
}

function isPlainRecord(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function extractMethodSpecsFromDefinition(
  definition?: Record<string, any> | null
): MethodSpec[] {
  if (!isPlainRecord(definition) || !isPlainRecord(definition.paths)) {
    return [];
  }

  const pathEntries = Object.entries(definition.paths as Record<string, any>);
  const methods: MethodSpec[] = [];

  for (const [path, operations] of pathEntries) {
    if (!isPlainRecord(operations)) {
      continue;
    }

    for (const [methodName, spec] of Object.entries(operations)) {
      if (!isPlainRecord(spec)) {
        continue;
      }

      if (!SUPPORTED_HTTP_METHODS.has(methodName.toLowerCase())) {
        continue;
      }

      const name = spec.operationId ?? spec.operationID;
      const summary = spec.summary ?? spec.description;

      if (!name || !summary) {
        continue;
      }

      methods.push({
        name,
        summary,
        path,
        method: methodName.toUpperCase(),
        spec,
        custom_headers: [],
      });
    }
  }

  return methods;
}

/**
 * The tooltip for an action row: what the tool does, plus how to turn it on
 * when it is not configured yet.
 */
export interface ToolTooltipMessages {
  descriptions: Record<string, string>;
  defaultDescription: string;
  configure: string;
  askAdmin: string;
}

export function buildTooltipMessage(
  actionDescription: string,
  isConfigured: boolean,
  canManageAction: boolean,
  messages: Pick<ToolTooltipMessages, "configure" | "askAdmin">
): string {
  if (isConfigured) return actionDescription;
  return canManageAction
    ? `${actionDescription} ${messages.configure}`
    : `${actionDescription} ${messages.askAdmin}`;
}

/** {@link buildTooltipMessage}, with the description resolved from the tool. */
export function getToolTooltip(
  tool: ToolSnapshot,
  isConfigured: boolean,
  canManageAction: boolean,
  messages: ToolTooltipMessages
): string {
  const description =
    (tool.in_code_tool_id && messages.descriptions[tool.in_code_tool_id]) ||
    tool.description ||
    messages.defaultDescription;
  return buildTooltipMessage(
    description,
    isConfigured,
    canManageAction,
    messages
  );
}

/** Where an admin configures this tool, or null when there is nowhere to go. */
export function getAdminConfigureInfo(
  tool: ToolSnapshot,
  configureTooltips: Record<string, string>
): { href: string; tooltip: string } | null {
  if (tool.in_code_tool_id && ADMIN_CONFIG_LINKS[tool.in_code_tool_id]) {
    const link = ADMIN_CONFIG_LINKS[tool.in_code_tool_id];
    if (!link) return null;
    return {
      href: link.href,
      tooltip: configureTooltips[tool.in_code_tool_id] ?? link.tooltip,
    };
  }
  if (!tool.in_code_tool_id && !tool.mcp_server_id) {
    return {
      href: OPENAPI_ADMIN_CONFIG.href,
      tooltip: configureTooltips.openapi ?? OPENAPI_ADMIN_CONFIG.tooltip,
    };
  }
  return null;
}
