import { redirect } from "next/navigation";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  parsePluginReference,
  pluginOpenHref,
  type PluginSearchParams,
} from "@/lib/plugins/routes";

// Plugin modals are not routes. Old detail links, such as an OAuth return
// started before they moved, open the plugin once on the Plugins page.
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ kind: string; id: string }>;
  searchParams: Promise<PluginSearchParams>;
}) {
  const { kind, id } = await params;
  const reference = parsePluginReference(`${kind}:${id}`);
  redirect(
    reference === null
      ? ADMIN_ROUTES.PLUGINS.path
      : pluginOpenHref(reference, await searchParams)
  );
}
