import { notFound } from "@opal/navigation";
import { parsePositiveId } from "@/lib/integrations/utils";
import IntegrationDetailPage from "@/sections/integrations/IntegrationDetailPage";

export default async function Page({
  params,
}: {
  params: Promise<{ integrationId: string }>;
}) {
  const { integrationId: value } = await params;
  const integrationId = parsePositiveId(value);
  if (integrationId === null) notFound();
  return (
    <IntegrationDetailPage key={integrationId} integrationId={integrationId} />
  );
}
