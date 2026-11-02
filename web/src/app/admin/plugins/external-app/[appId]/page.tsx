import { notFound } from "next/navigation";
import { parsePluginId } from "@/lib/plugins/routes";
import ExternalAppPluginDetail from "@/sections/plugins/ExternalAppPluginDetail";

export default async function Page({
  params,
}: {
  params: Promise<{ appId: string }>;
}) {
  const { appId: value } = await params;
  const appId = parsePluginId(value);
  if (appId === null) notFound();
  return <ExternalAppPluginDetail appId={appId} />;
}
