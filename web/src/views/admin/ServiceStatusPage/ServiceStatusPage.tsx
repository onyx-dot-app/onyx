"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { useTranslations } from "next-intl";
import { Button, SelectButton, Spacer } from "@opal/components";
import { Content, Section, SettingsLayouts, toast } from "@opal/layouts";
import { SvgPanelRight, SvgRefreshCw } from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  refreshClusterStatus,
  useClusterStatus,
} from "@/lib/service-status/hooks";
import ClusterSummaryCard from "@/views/admin/ServiceStatusPage/ClusterSummaryCard";
import DataNodesList from "@/views/admin/ServiceStatusPage/DataNodesList";
import IndexesList from "@/views/admin/ServiceStatusPage/IndexesList";
import IssuesPanel, {
  hasVisibleIssues,
} from "@/views/admin/ServiceStatusPage/IssuesPanel";
import SearchActivityCard from "@/views/admin/ServiceStatusPage/SearchActivityCard";
import PanelPageBody from "@/views/admin/connectors/shared/PanelPageBody";

const route = ADMIN_ROUTES.SERVICE_STATUS;

// PanelPageBody's stack point (51rem of page-body content) and panel width.
const PANEL_BESIDE = "@min-[51rem]:w-100 @min-[51rem]:shrink-0";

export default function ServiceStatusPage() {
  const t = useTranslations("admin.serviceStatus");
  const adminRouteTitle = useAdminRouteTitle();
  const { data, error, mutate } = useClusterStatus();
  const { mutate: mutateSwr } = useSWRConfig();
  const [refreshing, setRefreshing] = useState(false);
  // Unset until the admin toggles it: the panel then shows when an issue
  // shows, not counting dismissed warnings.
  const [panelOpen, setPanelOpen] = useState<boolean | null>(null);
  const showPanel = panelOpen ?? (data ? hasVisibleIssues(data.issues) : false);

  async function refresh() {
    setRefreshing(true);
    try {
      // The charts card fetches its own data; refresh it with the cluster.
      await Promise.all([
        mutate(refreshClusterStatus(), { revalidate: false }),
        mutateSwr(SWR_KEYS.serviceStatusSearches),
      ]);
    } catch {
      // The last result stays on the page.
      toast.error(t("page.refreshFailed"));
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <SettingsLayouts.Root
      width="xl"
      narrowGutters
      loading={!data && !error}
      // A failed background read keeps the last status on the page.
      error={error && !data ? t("page.loadFailed") : false}
    >
      <SettingsLayouts.Header
        icon={route.icon}
        title={adminRouteTitle(route)}
        description={t("page.description")}
        divider
        actions={[
          <Button
            key="refresh"
            prominence="secondary"
            icon={SvgRefreshCw}
            disabled={refreshing}
            onClick={refresh}
          >
            {t("page.refresh")}
          </Button>,
        ]}
      />
      {!data ? (
        // Shows the loader, or the error when the first read fails.
        <SettingsLayouts.Body />
      ) : (
        // The layout Indexing Status uses: the column, and the panel beside it
        // from 816px of content and under it below.
        <PanelPageBody
          panel={
            showPanel && (
              // Beside the column, the panel's 400px width from PanelPageBody's
              // stack point; stacked, the full width. It is a short card, so
              // it does not stretch or scroll like the Activities panel.
              <Section
                alignItems="stretch"
                width="full"
                height="fit"
                className={PANEL_BESIDE}
              >
                <IssuesPanel />
              </Section>
            )
          }
        >
          <Section gap={2} alignItems="stretch" height="fit">
            <Section
              flexDirection="row"
              justifyContent="between"
              alignItems="center"
              width="full"
            >
              <Content
                font="main-content-emphasis"
                title={t("cluster.title")}
              />
              <SelectButton
                icon={SvgPanelRight}
                size="md"
                state={showPanel ? "selected" : "empty"}
                tooltip={t("issues.title")}
                aria-label={t("issues.title")}
                onClick={() => setPanelOpen(!showPanel)}
              />
            </Section>
            <ClusterSummaryCard />
            <SearchActivityCard />
            {/* With the gaps on each side, 24px above each list, as in the design. */}
            <Spacer rem={0.5} />
            <DataNodesList />
            <Spacer rem={0.5} />
            <IndexesList />
          </Section>
        </PanelPageBody>
      )}
    </SettingsLayouts.Root>
  );
}
