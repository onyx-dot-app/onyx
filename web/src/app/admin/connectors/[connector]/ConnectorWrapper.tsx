"use client";

import { ConfigurableSources } from "@/lib/types";
import AddConnector from "./AddConnectorPage";
import { FormProvider } from "@/components/context/FormContext";
import Sidebar from "./Sidebar";
import { HeaderTitle } from "@/components/header/HeaderTitle";
import { Button } from "@/components/ui/button";
import { isValidSource, getSourceMetadata } from "@/lib/sources";
import { FederatedConnectorForm } from "@/components/admin/federated/FederatedConnectorForm";

export default function ConnectorWrapper({
  connector,
}: {
  connector: ConfigurableSources;
}) {
  // Check if the connector is valid
  if (!isValidSource(connector)) {
    return (
      <FormProvider connector={connector}>
        <div className="flex justify-center w-full h-full">
          <Sidebar />
          <div className="mt-12 w-full max-w-3xl mx-auto">
            <div className="mx-auto flex flex-col gap-y-2">
              <HeaderTitle>
                <p>&lsquo;{connector}&lsquo; is not a valid Connector Type!</p>
              </HeaderTitle>
              <Button
                onClick={() => window.open("/admin/indexing/status", "_self")}
                className="mr-auto"
              >
                {" "}
                Go home{" "}
              </Button>
            </div>
          </div>
        </div>
      </FormProvider>
    );
  }

  // Check if the connector is federated
  const sourceMetadata = getSourceMetadata(connector);
  const isFederated = sourceMetadata.federated;

  // For federated connectors, use the specialized form without FormProvider
  if (isFederated) {
    return (
      <div className="flex justify-center w-full h-full">
        <div className="mt-12 w-full max-w-4xl mx-auto">
          <FederatedConnectorForm connector={connector} />
        </div>
      </div>
    );
  }

  // For regular connectors, use the existing flow
  return (
    <FormProvider connector={connector}>
      <div className="flex justify-center w-full h-full">
        <Sidebar />
        <div className="mt-12 w-full max-w-3xl mx-auto">
          <AddConnector connector={connector} />
        </div>
      </div>
    </FormProvider>
  );
}
