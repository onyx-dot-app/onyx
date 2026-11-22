import { notFound } from "@opal/navigation";
import MemberPluginDetailPage from "@/sections/plugins/MemberPluginDetailPage";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function Page({
  params,
}: {
  params: Promise<{ pluginId: string }>;
}) {
  const { pluginId } = await params;
  if (!UUID.test(pluginId)) notFound();
  return <MemberPluginDetailPage key={pluginId} pluginId={pluginId} />;
}
