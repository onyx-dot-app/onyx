import ConnectorWrapper from "./ConnectorWrapper";

export default async function Page({
  params,
}: {
  params: { connector: string };
}) {
  return <ConnectorWrapper connector={params.connector.replace("-", "_")} />;
}
