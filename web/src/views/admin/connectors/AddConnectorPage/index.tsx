import { ConfigurableSources } from "@/lib/types";
import ConnectorWrapper from "@/views/admin/connectors/AddConnectorPage/ConnectorWrapper";

export interface PageProps {
  params: Promise<{ connector: string }>;
}

export default async function Page(props: PageProps) {
  const params = await props.params;
  return (
    <ConnectorWrapper
      connector={params.connector.replace("-", "_") as ConfigurableSources}
    />
  );
}
