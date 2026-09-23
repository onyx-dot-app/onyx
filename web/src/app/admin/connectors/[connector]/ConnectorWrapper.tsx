"use client";

import { useTranslations } from "next-intl";
import { ConfigurableSources } from "@/lib/types";
import AddConnector from "./AddConnectorPage";
import { Button } from "@opal/components";
import { SettingsLayouts, useToastFromQuery } from "@opal/layouts";
import { SvgAlertCircle } from "@opal/icons";
import { isValidSource, getSourceMetadata } from "@/lib/sources";
import { FederatedConnectorForm } from "@/components/admin/federated/FederatedConnectorForm";
import { useRouter, useSearchParams } from "next/navigation";

export default function ConnectorWrapper({
  connector,
}: {
  connector: ConfigurableSources;
}) {
  const t = useTranslations("admin.connectorsList");
  const router = useRouter();
  const searchParams = useSearchParams();
  const mode = searchParams?.get("mode"); // 'federated' or 'regular'

  useToastFromQuery({
    oauth_failed: {
      message: t("oauthFailed.toast"),
      type: "error",
    },
  });

  if (!isValidSource(connector)) {
    return (
      <SettingsLayouts.Root width="sm">
        <SettingsLayouts.Header
          icon={SvgAlertCircle}
          title={t("invalidConnector.title", { connector })}
        />
        <SettingsLayouts.Body>
          <div className="me-auto">
            <Button onClick={() => router.push("/admin/indexing-status")}>
              {t("invalidConnector.homeButton.label")}
            </Button>
          </div>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
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

  return <AddConnector connector={connector} />;
}
