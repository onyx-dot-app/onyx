import { SOURCE_METADATA_MAP } from "./sources";
import { ValidSources } from "./types";
import SvgServer from "@/icons/server";
import { MCPServer } from "./tools/interfaces";
import { DatabaseIcon, FileIcon } from "@/components/icons/icons";

/**
 * Get an appropriate icon for an MCP server based on its URL and name.
 * Leverages the existing SOURCE_METADATA_MAP for connector icons.
 *
 * @param server - The MCP server object (or compatible subset with server_url and name)
 * @returns A React component for the icon
 */
export function getMCPServerIcon(
  server: Pick<MCPServer, "server_url" | "name">
): React.ReactNode {
  const url = server.server_url.toLowerCase();
  const name = server.name.toLowerCase();

  // Try to match against known connector source types from SOURCE_METADATA_MAP
  for (const [sourceKey, metadata] of Object.entries(SOURCE_METADATA_MAP)) {
    const keyword = sourceKey.toLowerCase();

    if (url.includes(keyword) || name.includes(keyword)) {
      const Icon = metadata.icon;
      return <Icon size={20} />;
    }
  }

  // Additional patterns not in SOURCE_METADATA_MAP
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

  // Default to server icon
  return <SvgServer className="h-5 w-5 stroke-text-04" />;
}

/**
 * Get the display name from the SOURCE_METADATA_MAP if available,
 * otherwise return the provided name
 */
export function getMCPServerDisplayName(server: MCPServer): string {
  // You can extend this to map to known display names if needed
  return server.name;
}
