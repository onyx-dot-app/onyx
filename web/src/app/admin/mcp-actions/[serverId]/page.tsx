import { notFound, redirect } from "next/navigation";
import {
  parsePluginId,
  pluginDetailHref,
  withPluginSearchParams,
  type PluginSearchParams,
} from "@/lib/plugins/routes";

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ serverId: string }>;
  searchParams: Promise<PluginSearchParams>;
}) {
  const { serverId: value } = await params;
  const serverId = parsePluginId(value);
  if (serverId === null) notFound();
  redirect(
    withPluginSearchParams(
      pluginDetailHref({ kind: "mcp", id: serverId }),
      await searchParams
    )
  );
}
