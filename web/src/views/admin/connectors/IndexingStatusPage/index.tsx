"use client";

import { useTranslations } from "next-intl";
import { Section, SettingsLayouts, useToastFromQuery } from "@opal/layouts";
import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import ActivitiesCard from "@/views/admin/connectors/IndexingStatusPage/ActivitiesCard";
import ConnectorList from "@/views/admin/connectors/IndexingStatusPage/ConnectorList";
import OverviewCard from "@/views/admin/connectors/IndexingStatusPage/OverviewCard";

const route = ADMIN_ROUTES.INDEXING_STATUS;

/** Every connector's indexing at a glance: the fleet's throughput, then each connector with its latest run. */
export default function IndexingStatusPage() {
  const t = useTranslations("admin.indexing");
  const adminRouteTitle = useAdminRouteTitle();

  useToastFromQuery({
    "connector-created": {
      message: t("connectorCreated.toast"),
      type: "success",
    },
  });

  return (
    <SettingsLayouts.Root width="md">
      <SettingsLayouts.Header
        icon={route.icon}
        title={adminRouteTitle(route)}
        divider
      />
      <SettingsLayouts.Body>
        <Section alignItems="stretch" gap={4} height="fit">
          {/* The overview takes the wider share; both wrap to full width on a narrow screen. */}
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
              <OverviewCard />
            </Section>
            <Section
              alignItems="stretch"
              width="auto"
              height="auto"
              className="min-w-72 grow-[5] basis-0"
            >
              <ActivitiesCard />
            </Section>
          </Section>
          <ConnectorList />
        </Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
