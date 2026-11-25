import { notFound } from "@opal/navigation";
import { isPluginId } from "@/lib/customize/paths";
import MemberPluginDetailPage from "@/sections/plugins/MemberPluginDetailPage";

export default async function Page({
  params,
}: {
  params: Promise<{ pluginId: string }>;
}) {
  const { pluginId } = await params;
  if (!isPluginId(pluginId)) notFound();
  return <MemberPluginDetailPage key={pluginId} pluginId={pluginId} />;
}
