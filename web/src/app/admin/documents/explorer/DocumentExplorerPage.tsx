"use client";

import * as SettingsLayouts from "@/layouts/settings-layouts";
import { SvgZoomIn } from "@opal/icons";
import { Explorer } from "./Explorer";
import { Connector } from "@/lib/connectors/connectors";
import { DocumentSetSummary } from "@/lib/types";

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
      <SettingsLayouts.Header
        icon={SvgZoomIn}
        title="Document Explorer"
        separator
      />

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
