"use client";

import useSWR from "swr";
import { useFormatter, useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { StoredReportScope } from "@/lib/connectors/checks/findings";

interface MicrosoftRateBudgetEntry {
  connector_id: number;
  name: string;
  source: string;
  ru_per_minute: number | null;
}

interface MicrosoftRateBudgets {
  connectors: MicrosoftRateBudgetEntry[];
  total_ru_per_minute: number;
}

interface MicrosoftRateBudgetNoteProps {
  /** The credential of the form, and the connector that the form edits. */
  scope: StoredReportScope | null;
}

/**
 * One line under the "RU per minute" field: the values that the other
 * connectors on the same Microsoft app registration set, and their sum.
 * Microsoft limits the app, so the admin must keep the sum under its limit.
 */
export default function MicrosoftRateBudgetNote({
  scope,
}: MicrosoftRateBudgetNoteProps) {
  const t = useTranslations("admin.connectorsList");
  const format = useFormatter();
  const { data } = useSWR<MicrosoftRateBudgets>(
    scope === null
      ? null
      : SWR_KEYS.microsoftRateBudgets(scope.credentialId, scope.connectorId),
    errorHandlingFetcher
  );
  if (!data) return null;

  const withValue = data.connectors.filter(
    (connector) => connector.ru_per_minute !== null
  );
  return (
    <Text font="secondary-body" color="text-03" as="p">
      {withValue.length === 0
        ? t("connectors.microsoft.fields.ru_per_minute.none")
        : t("connectors.microsoft.fields.ru_per_minute.others", {
            connectors: withValue
              .map(
                (connector) =>
                  `${connector.name} (${format.number(connector.ru_per_minute ?? 0)})`
              )
              .join(", "),
            total: format.number(data.total_ru_per_minute),
          })}
    </Text>
  );
}
