import { SOURCE_METADATA_MAP } from "../sources";
import { MCPServer } from "./interfaces";
import { DatabaseIcon, FileIcon } from "@/components/icons/icons";
import type { IconProps } from "@opal/types";
import { SvgServer } from "@opal/icons";

/**
 * Get an appropriate icon for an MCP server based on its URL and name.
 * Leverages the existing SOURCE_METADATA_MAP for connector icons.
 */
export function getMCPServerIcon(
  server: Pick<MCPServer, "server_url" | "name">
): React.FunctionComponent<IconProps> {
  const url = server.server_url.toLowerCase();
  const name = server.name.toLowerCase();

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

export function getMCPServerDisplayName(server: MCPServer): string {
  return server.name;
}
