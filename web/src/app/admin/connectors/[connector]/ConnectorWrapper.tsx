"use client";

import {
  ConfigurableSources,
  FederatedConnectorDetail,
  federatedSourceToRegularSource,
  ValidSources,
} from "@/lib/types";
import AddConnector from "./AddConnectorPage";
import { FormProvider } from "@/components/context/FormContext";
import CreateConnectorSidebar, {
  CreateConnectorSidebarShell,
} from "@/sections/sidebar/CreateConnectorSidebar";
import { AdminCustomSidebarPortal } from "@/layouts/chromes/AdminChrome";
import { HeaderTitle } from "@/components/header/HeaderTitle";
import { Button } from "@opal/components";
import { isValidSource, getSourceMetadata } from "@/lib/sources";
import { FederatedConnectorForm } from "@/components/admin/federated/FederatedConnectorForm";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";
import { Credential } from "@/lib/connectors/credentials";
import { useFederatedConnectors } from "@/lib/hooks";
import Text from "@/refresh-components/texts/Text";
import { useToastFromQuery } from "@opal/layouts";

export default function ConnectorWrapper({
  connector,
}: {
  connector: ConfigurableSources;
}) {
  const searchParams = useSearchParams();
  const mode = searchParams?.get("mode"); // 'federated' or 'regular'

  useToastFromQuery({
    oauth_failed: {
      message: "OAuth authentication failed. Please try again.",
      type: "error",
    },
  });

  // Check if the connector is valid
  if (!isValidSource(connector)) {
    return (
      <FormProvider connector={connector}>
        <AdminCustomSidebarPortal>
          <CreateConnectorSidebar />
        </AdminCustomSidebarPortal>
        <div className="mt-12 w-full max-w-3xl mx-auto">
          <div className="mx-auto flex flex-col gap-y-2">
            <HeaderTitle>
              <p>&lsquo;{connector}&rsquo; is not a valid Connector Type!</p>
            </HeaderTitle>
            <div className="mr-auto">
              <Button
                onClick={() => window.open("/admin/indexing/status", "_self")}
              >
                Go home
              </Button>
            </div>
          </div>
        </div>
      </FormProvider>
    );
  }

  const sourceMetadata = getSourceMetadata(connector);
  const supportsFederated = sourceMetadata.federated === true;

  // Only show federated form if explicitly requested via URL parameter
  const showFederatedForm = mode === "federated" && supportsFederated;

  // For federated form, use the specialized form without FormProvider.
  // That form is a single page, so its sidebar shows no steps.
  if (showFederatedForm) {
    return (
      <>
        <AdminCustomSidebarPortal>
          <CreateConnectorSidebarShell />
        </AdminCustomSidebarPortal>
        <div className="flex justify-center w-full h-full">
          <div className="mt-12 w-full max-w-4xl mx-auto">
            <FederatedConnectorForm connector={connector} />
          </div>
        </div>
      </>
    );
  }

  // For regular connectors, use the existing flow
  return (
    <FormProvider connector={connector}>
      <AdminCustomSidebarPortal>
        <CreateConnectorSidebar />
      </AdminCustomSidebarPortal>
      <div className="mt-12 w-full max-w-3xl mx-auto">
        <AddConnector connector={connector} />
      </div>
    </FormProvider>
  );
}
