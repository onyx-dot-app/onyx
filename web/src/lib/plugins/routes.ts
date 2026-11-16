import { ADMIN_ROUTES } from "@/lib/admin-routes";
import type { PluginReference } from "@/lib/plugins/types";

export type PluginSearchParams = Record<string, string | string[] | undefined>;
type PluginDetailPath = `/admin/plugins/${PluginReference["kind"]}/${number}`;
type PluginPath = typeof ADMIN_ROUTES.PLUGINS.path | PluginDetailPath;

export function pluginDetailHref(reference: PluginReference): PluginDetailPath {
  return `${ADMIN_ROUTES.PLUGINS.path}/${reference.kind}/${reference.id}`;
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
