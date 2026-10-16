"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Section, SettingsLayouts, useToastFromQuery } from "@opal/layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import ActivityPanel from "@/views/admin/connectors/ConnectorDetailPage/ActivityPanel";
import ActivitiesCard from "@/views/admin/connectors/IndexingStatusPage/ActivitiesCard";
import ConnectorList from "@/views/admin/connectors/IndexingStatusPage/ConnectorList";
import OverviewCard from "@/views/admin/connectors/IndexingStatusPage/OverviewCard";
import type { SliceRange } from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";

const route = ADMIN_ROUTES.INDEXING_STATUS;

/** Every connector's indexing at a glance: the fleet's throughput and newest failures, then each connector with its latest run. */
export default function IndexingStatusPage() {
  const t = useTranslations("admin.indexing");
  const [historyOpen, setHistoryOpen] = useState(false);
  // A clicked chart slice narrows the history panel, which opens to show it.
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
                    setHistoryOpen(true);
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
                  <ActivitiesCard onOpenHistory={() => setHistoryOpen(true)} />
                </Section>
              )}
            </Section>
            <ConnectorList />
          </Section>
          {historyOpen && (
            // Stacked on a narrow screen, the history keeps the Activities card's place above the list.
            <ActivityPanel
              scope="fleet"
              title={t("activities.panel.title")}
              onClose={() => {
                setHistoryOpen(false);
                setRange(null);
              }}
              range={range}
              onClearRange={() => setRange(null)}
              className="max-lg:order-first"
            />
          )}
        </Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
