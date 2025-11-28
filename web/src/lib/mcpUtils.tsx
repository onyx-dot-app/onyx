import { SOURCE_METADATA_MAP } from "./sources";
import SvgServer from "@/icons/server";
import { MCPServer } from "./tools/interfaces";
import { DatabaseIcon, FileIcon } from "@/components/icons/icons";

/**
 * Get an appropriate icon for an MCP server based on its URL and name.
 * Leverages the existing SOURCE_METADATA_MAP for connector icons.
 */
export function getMCPServerIcon(
  server: Pick<MCPServer, "server_url" | "name">
): React.ReactNode {
  const url = server.server_url.toLowerCase();
  const name = server.name.toLowerCase();

  for (const [sourceKey, metadata] of Object.entries(SOURCE_METADATA_MAP)) {
    const keyword = sourceKey.toLowerCase();

    if (url.includes(keyword) || name.includes(keyword)) {
      const Icon = metadata.icon;
      return <Icon size={20} />;
    }
  }

  if (
    url.includes("postgres") ||
    url.includes("mysql") ||
    url.includes("mongodb") ||
    url.includes("redis")
  ) {
    return <DatabaseIcon size={20} />;
  }
  if (url.includes("filesystem") || name.includes("file system")) {
    return <FileIcon size={20} />;
  }

  return <SvgServer className="h-5 w-5 stroke-text-04" />;
}

export function getMCPServerDisplayName(server: MCPServer): string {
  return server.name;
}
