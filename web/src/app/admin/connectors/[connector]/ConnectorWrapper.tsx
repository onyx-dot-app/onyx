"use client";

import { ConfigurableSources } from "@/lib/types";
import AddConnector from "./AddConnectorPage";
import { FormProvider } from "@/components/context/FormContext";
import Sidebar from "../../../../sections/sidebar/CreateConnectorSidebar";
import { HeaderTitle } from "@/components/header/HeaderTitle";
import { Button } from "@/components/ui/button";
import { isValidSource, getSourceMetadata } from "@/lib/sources";
import { FederatedConnectorForm } from "@/components/admin/federated/FederatedConnectorForm";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";
import { Credential } from "@/lib/connectors/credentials";

export default function ConnectorWrapper({
  connector,
}: {
  connector: ConfigurableSources;
}) {
  const searchParams = useSearchParams();
  const mode = searchParams?.get("mode"); // 'federated' or 'regular'

  // Fetch existing credentials for this connector type
  const { data: existingCredentials } = useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(connector),
    errorHandlingFetcher
  );

  // Check if the connector is valid
  if (!isValidSource(connector)) {
    return (
      <FormProvider connector={connector}>
        <div className="flex justify-center w-full h-full">
          <Sidebar />
          <div className="mt-12 w-full max-w-3xl mx-auto">
            <div className="mx-auto flex flex-col gap-y-2">
              <HeaderTitle>
                <p>&lsquo;{connector}&rsquo; is not a valid Connector Type!</p>
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

  const sourceMetadata = getSourceMetadata(connector);
  const supportsFederated = sourceMetadata.federated === true;
  const hasExistingCredentials =
    existingCredentials && existingCredentials.length > 0;

  // Determine which form to show based on:
  // 1. URL parameter mode (takes priority)
  // 2. If no mode specified and existing credentials exist, show regular form
  // 3. If no mode specified and no credentials, show federated form for federated-supported sources
  let showFederatedForm = false;

  if (mode === "federated") {
    showFederatedForm = supportsFederated;
  } else if (mode === "regular") {
    showFederatedForm = false;
  } else {
    // No mode specified - use default logic
    if (hasExistingCredentials) {
      // Default to regular form if existing credentials exist
      showFederatedForm = false;
    } else {
      // Default to federated for federated-supported sources with no existing credentials
      showFederatedForm = supportsFederated;
    }
  }

  // For federated form, use the specialized form without FormProvider
  if (showFederatedForm) {
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
