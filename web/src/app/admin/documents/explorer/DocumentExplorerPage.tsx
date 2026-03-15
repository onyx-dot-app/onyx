"use client";

import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Explorer } from "./Explorer";
import { Connector } from "@/lib/connectors/connectors";
import { DocumentSetSummary } from "@/lib/types";

const route = ADMIN_ROUTES.DOCUMENT_EXPLORER;

interface DocumentExplorerPageProps {
  initialSearchValue: string | undefined;
  connectors: Connector<any>[];
  documentSets: DocumentSetSummary[];
}

export default function DocumentExplorerPage({
  initialSearchValue,
  connectors,
  documentSets,
}: DocumentExplorerPageProps) {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} separator />

      <SettingsLayouts.Body>
        <Explorer
          initialSearchValue={initialSearchValue}
          connectors={connectors}
          documentSets={documentSets}
        />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
