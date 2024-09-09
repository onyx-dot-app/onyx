import { ConfigurableSources } from "@/lib/types";
import ConnectorWrapper from "./ConnectorWrapper";

export default async function Page({
  params,
}: {
  params: { connector: string };
}) {
  return (
    <ConnectorWrapper
      connector={params.connector.replace("-", "_") as ConfigurableSources}
    />
  );
}
