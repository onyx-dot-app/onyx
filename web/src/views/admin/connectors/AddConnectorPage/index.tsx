import type { ConfigurableSources } from "@/lib/connectors/types/source";
import AddConnectorWrapper from "@/views/admin/connectors/AddConnectorPage/components/AddConnectorWrapper";

export interface PageProps {
  params: Promise<{ connector: string }>;
}

export default async function Page(props: PageProps) {
  const params = await props.params;
  return (
    <AddConnectorWrapper
      connector={params.connector.replace("-", "_") as ConfigurableSources}
    />
  );
}
