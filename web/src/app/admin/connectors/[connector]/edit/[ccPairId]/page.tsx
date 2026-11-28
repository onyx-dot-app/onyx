import EditConnectorPage from "@/views/admin/connectors/EditConnectorPage";

export interface PageProps {
  params: Promise<{ connector: string; ccPairId: string }>;
}

export default async function Page(props: PageProps) {
  const params = await props.params;
  return (
    <EditConnectorPage
      source={params.connector.replace("-", "_")}
      ccPairId={Number(params.ccPairId)}
    />
  );
}
