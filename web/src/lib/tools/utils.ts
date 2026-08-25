import { SOURCE_METADATA_MAP } from "@/lib/sources";
import { MethodSpec } from "@/lib/tools/types";
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
