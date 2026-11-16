import { notFound } from "@opal/navigation";
import { parseIntegrationId } from "@/lib/integrations/utils";
import IntegrationDetailPage from "@/sections/integrations/IntegrationDetailPage";

export default async function Page({
  params,
}: {
  params: Promise<{ integrationId: string }>;
}) {
  const { integrationId: value } = await params;
  const integrationId = parseIntegrationId(value);
  if (integrationId === null) notFound();
  return (
    <IntegrationDetailPage key={integrationId} integrationId={integrationId} />
  );
}
