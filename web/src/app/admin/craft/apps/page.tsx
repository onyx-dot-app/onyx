import { redirect } from "next/navigation";
import {
  pluginDetailHref,
  parsePluginId,
  withPluginSearchParams,
} from "@/lib/plugins/routes";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const value = query.editAppId ?? query.configureAppId ?? query.appId;
  const id = typeof value === "string" ? parsePluginId(value) : null;
  const rest = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (["editAppId", "configureAppId", "appId", "tab"].includes(key)) continue;
    if (typeof value === "string") rest.set(key, value);
    else if (Array.isArray(value))
      for (const item of value) rest.append(key, item);
  }
  redirect(
    withPluginSearchParams(
      id === null
        ? ADMIN_ROUTES.PLUGINS.path
        : pluginDetailHref({ kind: "external-app", id }),
      rest
    )
  );
}
