"use client";

import { useTranslations } from "next-intl";
import { Section, SettingsLayouts, useToastFromQuery } from "@opal/layouts";
import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
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
          <OverviewCard />
          <ConnectorList />
        </Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
