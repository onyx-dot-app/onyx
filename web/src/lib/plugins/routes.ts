import { ADMIN_ROUTES } from "@/lib/admin-routes";
import type { PluginReference } from "@/lib/plugins/types";

export type PluginSearchParams = Record<string, string | string[] | undefined>;
type PluginPath = typeof ADMIN_ROUTES.PLUGINS.path;
type PluginHref = PluginPath | `${PluginPath}?${string}`;

/** The query parameter that opens a plugin's modal once on the Plugins page. */
export const OPEN_PLUGIN_PARAM = "plugin";

/**
 * The Plugins page with a plugin's modal opened once, for flows that leave
 * the app and come back (OAuth sign-in) or old links. Other parameters are
 * handed to the modal, then the page clears them all.
 */
export function pluginOpenHref(
  reference: PluginReference,
  params: PluginSearchParams | URLSearchParams = {}
): PluginHref {
  return withPluginSearchParams(
    ADMIN_ROUTES.PLUGINS.path,
    params,
    `${OPEN_PLUGIN_PARAM}=${reference.kind}:${reference.id}`
  );
}

/** Reads `plugin=<kind>:<id>`; anything else is null. */
export function parsePluginReference(
  value: string | null
): PluginReference | null {
  if (!value) return null;
  const separator = value.lastIndexOf(":");
  const kind = value.slice(0, separator);
  const id = parsePluginId(value.slice(separator + 1));
  if (separator < 1 || id === null) return null;
  if (kind === "mcp" || kind === "openapi" || kind === "external-app")
    return { kind, id };
  return null;
}

export function mcpOAuthReturnHref(
  serverId: number,
  enableChat = false
): PluginHref {
  return pluginOpenHref(
    { kind: "mcp", id: serverId },
    enableChat
      ? { trigger_fetch: "true", enable_chat: "true" }
      : { trigger_fetch: "true" }
  );
}

export function parsePluginId(value: string | undefined): number | null {
  if (!value || !/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

export function withPluginSearchParams<Path extends PluginPath>(
  pathname: Path,
  searchParams: PluginSearchParams | URLSearchParams,
  initialQuery = ""
): Path | `${Path}?${string}` {
  const query = new URLSearchParams(initialQuery);
  if (searchParams instanceof URLSearchParams) {
    for (const [key, value] of searchParams) query.append(key, value);
  } else {
    for (const [key, value] of Object.entries(searchParams)) {
      if (Array.isArray(value)) {
        for (const item of value) query.append(key, item);
      } else if (value !== undefined) {
        query.append(key, value);
      }
    }
  }
  const queryString = query.toString();
  return queryString ? `${pathname}?${queryString}` : pathname;
}

export function legacyMcpListHref(
  searchParams: PluginSearchParams
): PluginHref {
  const value = searchParams.server_id;
  const serverId = parsePluginId(Array.isArray(value) ? value[0] : value);
  return serverId === null
    ? withPluginSearchParams(ADMIN_ROUTES.PLUGINS.path, searchParams)
    : pluginOpenHref({ kind: "mcp", id: serverId }, searchParams);
}
