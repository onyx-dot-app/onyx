import { ConfigurableSources } from "@/lib/types";
import ConnectorWrapper from "./ConnectorWrapper";

export default async function Page(props: {
  params: Promise<{ connector: string }>;
}) {
  const params = await props.params;
  return (
    <div
      className="min-h-screen w-screen bg-background"
      style={{
        ["--background-input-background" as any]: "#FAFAFA",
        ["--background" as any]: "#FAFAFA",
        ["--background-chatbar-sidebar" as any]: "#F0F0F1",
      }}
    >
      <ConnectorWrapper
        connector={params.connector.replace("-", "_") as ConfigurableSources}
      />
    </div>
  );
}
