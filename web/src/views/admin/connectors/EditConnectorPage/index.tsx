"use client";

import useSWR from "swr";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Button } from "@opal/components";
import {
  IllustrationContent,
  PageCenter,
  SettingsLayouts,
} from "@opal/layouts";
import { PageLoader } from "@opal/loaders";
import { SvgPlugBroken } from "@opal/illustrations";
import { SvgAlertCircle } from "@opal/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import { connectorConfigs } from "@/lib/connectors/connectors";
import type { CCPairFullInfo } from "@/lib/connectors/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import { AddConnectorForm } from "@/views/admin/connectors/AddConnectorPage/components/AddConnectorWrapper";

function isConfigurableSource(source: string): source is ConfigurableSources {
  return Object.hasOwn(connectorConfigs, source);
}

export interface EditConnectorPageProps {
  /** The source in the URL; it must match the pair's source. */
  source: string;
  ccPairId: number;
}

/**
 * The connector creation form in edit mode, filled with the pair's current
 * state. Submitting it computes a plan instead of creating a connector.
 */
export default function EditConnectorPage({
  source,
  ccPairId,
}: EditConnectorPageProps) {
  const t = useTranslations("admin.connectorEdit");
  const router = useRouter();
  // No polling: the form keeps the values it was filled with.
  const { data: ccPair, error } = useSWR<CCPairFullInfo>(
    buildCCPairInfoUrl(ccPairId),
    errorHandlingFetcher,
    { revalidateOnFocus: false, revalidateOnReconnect: false }
  );

  const pairSource = ccPair?.connector.source;
  const failed =
    error !== undefined ||
    (pairSource !== undefined &&
      (pairSource !== source || !isConfigurableSource(pairSource)));

  if (failed) {
    return (
      <SettingsLayouts.Root width="sm">
        <SettingsLayouts.Header
          icon={SvgAlertCircle}
          title={t("loadError.title")}
          actions={[
            <Button
              key="back"
              prominence="secondary"
              onClick={() => router.push(`/admin/connector/${ccPairId}`)}
            >
              {t("loadError.backButton.label")}
            </Button>,
          ]}
        />
        <SettingsLayouts.Body>
          <PageCenter>
            <IllustrationContent
              illustration={SvgPlugBroken}
              title={t("loadError.title")}
              description={t("loadError.description")}
            />
          </PageCenter>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  if (
    ccPair === undefined ||
    pairSource === undefined ||
    !isConfigurableSource(pairSource)
  ) {
    return <PageLoader />;
  }

  return <AddConnectorForm connector={pairSource} edit={{ ccPair }} />;
}
