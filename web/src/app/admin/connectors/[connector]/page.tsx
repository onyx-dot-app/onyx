import { ConfigurableSources } from "@/lib/types";
import ConnectorWrapper from "./ConnectorWrapper";

export default async function Page(props: {
  params: Promise<{ connector: string }>;
}) {
  const params = await props.params;
  return (
    <ConnectorWrapper
      connector={params.connector.replace("-", "_") as ConfigurableSources}
    />
  );
}
