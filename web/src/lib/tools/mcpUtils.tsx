import { SOURCE_METADATA_MAP } from "../sources";
import { MCPServer } from "./interfaces";
import { DatabaseIcon, FileIcon } from "@/components/icons/icons";
import type { IconProps } from "@opal/types";
import { SvgServer } from "@opal/icons";

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
    return DatabaseIcon;
  }
  if (url.includes("filesystem") || name.includes("file system")) {
    return FileIcon;
  }

  return SvgServer;
}
