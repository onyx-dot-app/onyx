import { notFound } from "next/navigation";
import { parsePluginId } from "@/lib/plugins/routes";
import MCPPluginDetailPage from "@/views/admin/PluginsPage/MCPPluginDetailPage";

export default async function Page({
  params,
}: {
  params: Promise<{ serverId: string }>;
}) {
  const { serverId: value } = await params;
  const serverId = parsePluginId(value);
  if (serverId === null) notFound();
  return <MCPPluginDetailPage key={serverId} serverId={serverId} />;
}
