import { notFound } from "next/navigation";
import { parsePluginId } from "@/lib/plugins/routes";
import OpenAPIPluginModal from "@/views/admin/PluginsPage/OpenAPIPluginModal";

export default async function Page({
  params,
}: {
  params: Promise<{ toolId: string }>;
}) {
  const { toolId: value } = await params;
  const toolId = parsePluginId(value);
  if (toolId === null) notFound();
  return <OpenAPIPluginModal key={toolId} toolId={toolId} />;
}
