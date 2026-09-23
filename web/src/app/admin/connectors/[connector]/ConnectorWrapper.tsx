"use client";

import { useTranslations } from "next-intl";
import {
  ConfigurableSources,
  FederatedConnectorDetail,
  federatedSourceToRegularSource,
  ValidSources,
} from "@/lib/types";
import AddConnector from "./AddConnectorPage";
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
  const t = useTranslations("admin.connectorsList");
  const searchParams = useSearchParams();
  const mode = searchParams?.get("mode"); // 'federated' or 'regular'

  useToastFromQuery({
    oauth_failed: {
      message: t("oauthFailed.toast"),
      type: "error",
    },
  });

  // Check if the connector is valid
  if (!isValidSource(connector)) {
    return (
      <div className="mt-12 w-full max-w-3xl mx-auto">
        <div className="mx-auto flex flex-col gap-y-2">
          <HeaderTitle>
            <p>{t("invalidConnector.title", { connector })}</p>
          </HeaderTitle>
          <div className="me-auto">
            <Button
              onClick={() => window.open("/admin/indexing-status", "_self")}
            >
              {t("invalidConnector.homeButton.label")}
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const sourceMetadata = getSourceMetadata(connector);
  const supportsFederated = sourceMetadata.federated === true;

  // Only show federated form if explicitly requested via URL parameter
  const showFederatedForm = mode === "federated" && supportsFederated;

  if (showFederatedForm) {
    return (
      <div className="flex justify-center w-full h-full">
        <div className="mt-12 w-full max-w-4xl mx-auto">
          <FederatedConnectorForm connector={connector} />
        </div>
      </div>
    );
  }

  return (
    <div className="mt-12 w-full max-w-3xl mx-auto">
      <AddConnector connector={connector} />
    </div>
  );
}
