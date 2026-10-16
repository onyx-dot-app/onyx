"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Section, SettingsLayouts, useToastFromQuery } from "@opal/layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import type {
  CCPairFullInfo,
  IndexingConnectorRow,
} from "@/lib/connectors/types";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { can } from "@/lib/permissions/resource-actions";
import ActivityPanel from "@/views/admin/connectors/ConnectorDetailPage/ActivityPanel";
import ActivitiesCard from "@/views/admin/connectors/IndexingStatusPage/ActivitiesCard";
import ConnectorList from "@/views/admin/connectors/IndexingStatusPage/ConnectorList";
import OverviewCard from "@/views/admin/connectors/IndexingStatusPage/OverviewCard";
import type { SliceRange } from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";

const route = ADMIN_ROUTES.INDEXING_STATUS;

interface PairActivityPanelProps {
  row: IndexingConnectorRow;
  onClose: () => void;
}

/** The history panel on one connector's runs, opened from its row. */
function PairActivityPanel({ row, onClose }: PairActivityPanelProps) {
  const t = useTranslations("admin.indexing");
  // The row does not say whether its source resolves errors one by one, so the pair's details do.
  const { data: ccPair } = useSWR<CCPairFullInfo>(
    buildCCPairInfoUrl(row.cc_pair_id),
    errorHandlingFetcher
  );
  return (
    <ActivityPanel
      scope={{
        ccPairId: row.cc_pair_id,
        canResolve:
          ccPair !== undefined &&
          can(ccPair, "operate") &&
          ccPair.supports_targeted_reindex,
        canResolveRuns: can(row, "operate"),
      }}
      title={t("activities.panel.pairTitle", { name: row.name })}
      onClose={onClose}
      className="max-lg:order-first"
    />
  );
}

/** Every connector's indexing at a glance: the fleet's throughput and newest failures, then each connector with its latest run. */
export default function IndexingStatusPage() {
  const t = useTranslations("admin.indexing");
  // The fleet's history, or one connector's.
  const [history, setHistory] = useState<"fleet" | IndexingConnectorRow | null>(
    null
  );
  const historyOpen = history !== null;
  // A clicked chart slice narrows the fleet's history, which opens to show it.
  const [range, setRange] = useState<SliceRange | null>(null);

  useToastFromQuery({
    "connector-created": {
      message: t("connectorCreated.toast"),
      type: "success",
    },
  });

  // The history panel takes the Activities card's place and widens the page to fit beside the column.
  return (
    <SettingsLayouts.Root width={historyOpen ? "xl" : "md"}>
      <SettingsLayouts.Header icon={route.icon} title={t("title")} divider />
      <SettingsLayouts.Body>
        <Section
          flexDirection="row"
          alignItems="start"
          gap={4}
          height="fit"
          className="max-lg:flex-col"
        >
          <Section
            alignItems="stretch"
            gap={4}
            height="fit"
            className="min-w-0 flex-1"
          >
            {/* The overview takes the wider share. Both wrap to full width on a narrow screen. */}
            <Section
              flexDirection="row"
              alignItems="stretch"
              gap={2}
              height="fit"
              wrap
            >
              <Section
                alignItems="stretch"
                width="auto"
                height="auto"
                className="min-w-80 grow-[8] basis-0"
              >
                <OverviewCard
                  onSliceClick={(start, end) => {
                    setRange({
                      since: start.toISOString(),
                      until: end.toISOString(),
                    });
                    setHistory("fleet");
                  }}
                />
              </Section>
              {!historyOpen && (
                <Section
                  alignItems="stretch"
                  width="auto"
                  height="auto"
                  className="min-w-72 grow-[5] basis-0"
                >
                  <ActivitiesCard onOpenHistory={() => setHistory("fleet")} />
                </Section>
              )}
            </Section>
            <ConnectorList
              onViewLogs={(row) => {
                setHistory(row);
                setRange(null);
              }}
            />
          </Section>
          {/* Stacked on a narrow screen, the history keeps the Activities card's place above the list. */}
          {history === "fleet" ? (
            <ActivityPanel
              scope="fleet"
              title={t("activities.panel.title")}
              onClose={() => {
                setHistory(null);
                setRange(null);
              }}
              range={range}
              onClearRange={() => setRange(null)}
              className="max-lg:order-first"
            />
          ) : (
            history !== null && (
              <PairActivityPanel
                key={history.cc_pair_id}
                row={history}
                onClose={() => setHistory(null)}
              />
            )
          )}
        </Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
