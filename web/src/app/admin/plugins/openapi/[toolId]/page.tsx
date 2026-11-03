import { notFound } from "next/navigation";
import { parsePluginId } from "@/lib/plugins/routes";
import OpenAPIPluginDetailPage from "@/sections/plugins/OpenAPIPluginDetailPage";

export default async function Page({
  params,
}: {
  params: Promise<{ toolId: string }>;
}) {
  const { toolId: value } = await params;
  const toolId = parsePluginId(value);
  if (toolId === null) notFound();
  return <OpenAPIPluginDetailPage key={toolId} toolId={toolId} />;
}
