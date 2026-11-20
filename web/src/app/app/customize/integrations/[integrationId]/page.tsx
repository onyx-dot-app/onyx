import { notFound } from "@opal/navigation";
import CustomizeIntegrationPage from "@/sections/customize/CustomizeIntegrationPage";

interface PageProps {
  params: Promise<{ integrationId: string }>;
}

export default async function Page({ params }: PageProps) {
  const { integrationId } = await params;
  const id = Number(integrationId);
  if (!Number.isInteger(id) || id <= 0) notFound();
  return <CustomizeIntegrationPage key={id} integrationId={id} />;
}
