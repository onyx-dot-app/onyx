import { notFound } from "next/navigation";
import { parsePluginId } from "@/lib/plugins/routes";
import ExternalAppPluginDetailPage from "@/views/admin/PluginsPage/ExternalAppPluginDetailPage";

export default async function Page({
  params,
}: {
  params: Promise<{ appId: string }>;
}) {
  const { appId: value } = await params;
  const appId = parsePluginId(value);
  if (appId === null) notFound();
  return <ExternalAppPluginDetailPage appId={appId} />;
}
