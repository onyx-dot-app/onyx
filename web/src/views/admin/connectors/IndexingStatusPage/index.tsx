"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, SelectButton } from "@opal/components";
import { Section, SettingsLayouts } from "@opal/layouts";
import { SvgPanelRight, SvgPlus } from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import type {
  CCPairFullInfo,
  IndexingConnectorRow,
} from "@/lib/connectors/types";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { can } from "@/lib/permissions/resource-actions";
import {
  useActivityChartLinks,
  useActivityPanelOpen,
} from "@/lib/connectors/ccPair/hooks";
import ActivityPanel from "@/views/admin/connectors/ConnectorDetailPage/ActivityPanel";
import ConnectorList from "@/views/admin/connectors/IndexingStatusPage/ConnectorList";
import OverviewCard from "@/views/admin/connectors/IndexingStatusPage/OverviewCard";
import { focusDimClass } from "@/views/admin/connectors/ConnectorDetailPage/focusMode";
import type { SliceRange } from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";
import PanelPageBody, {
  BESIDE,
  isStacked,
} from "@/views/admin/connectors/shared/PanelPageBody";

const route = ADMIN_ROUTES.INDEXING_STATUS;

/** Stacked, the history sits under the list and out of view, so it scrolls there. */
export function revealHistory(panel: HTMLDivElement | null) {
  if (panel === null || !isStacked(panel)) return;
  panel.scrollIntoView({ block: "start", behavior: "smooth" });
}

interface StackedPanelToggleProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Shows or hides the history from the end of the list, where the stacked panel sits, since the counts card's button goes when stacked. */
function StackedPanelToggle({ open, onOpenChange }: StackedPanelToggleProps) {
  const t = useTranslations("admin.indexing.activities");
  return (
    <Section
      flexDirection="row"
      justifyContent="end"
      height="fit"
      className={BESIDE.hiddenBeside}
    >
      <SelectButton
        icon={SvgPanelRight}
        size="md"
        state={open ? "selected" : "empty"}
        tooltip={t(open ? "panelButton.hide" : "panelButton.show")}
        onClick={() => onOpenChange(!open)}
      >
        {t("panel.title")}
      </SelectButton>
    </Section>
  );
}

interface PairActivityPanelProps {
  row: IndexingConnectorRow;
  onClose: () => void;
  onHoverPair: (ccPairId: number | null) => void;
  ref: React.Ref<HTMLDivElement>;
}

/** The history panel on one connector's runs, opened from its row. */
function PairActivityPanel({
  row,
  onClose,
  onHoverPair,
  ref,
}: PairActivityPanelProps) {
  const t = useTranslations("admin.indexing");
  // The row does not say whether its source resolves errors one by one, so the pair's details do.
  const { data: ccPair } = useSWR<CCPairFullInfo>(
    buildCCPairInfoUrl(row.cc_pair_id),
    errorHandlingFetcher
  );
  // Both flags come from the details, so a supported connector never reads as unsupported while they load.
  const operates = ccPair !== undefined && can(ccPair, "operate");
  return (
    <ActivityPanel
      scope={{
        ccPairId: row.cc_pair_id,
        canResolve: operates && ccPair.supports_targeted_reindex,
        canResolveRuns: operates,
      }}
      title={t("activities.panel.pairTitle", { name: row.name })}
      onClose={onClose}
      onHoverPair={onHoverPair}
      sticky
      ref={ref}
    />
  );
}

/** Every connector's indexing at a glance: the fleet's counts and throughput, then each connector with its latest run, beside the fleet's activities. */
export default function IndexingStatusPage() {
  const t = useTranslations("admin.indexing");
  // The catalog's route needs global connector management, which a scoped manager does not hold.
  const { isGlobalHolder: canAddConnector } = usePermissionAuthority(
    Permission.MANAGE_CONNECTORS
  );
  // One connector's history takes the fleet's place while it is open.
  const [pairHistory, setPairHistory] = useState<IndexingConnectorRow | null>(
    null
  );
  // A picked span of the chart narrows the fleet's history, which opens to show it.
  const [range, setRange] = useState<SliceRange | null>(null);
  const fleetPanel = useActivityPanelOpen("fleet");
  const history: "fleet" | IndexingConnectorRow | null =
    pairHistory ?? (fleetPanel.open ? "fleet" : null);
  const historyOpen = history !== null;
  // The history the page opens with stays where it is. Only one the admin picks scrolls into view.
  const adminPicked = useRef(false);
  function showFleetHistory() {
    adminPicked.current = true;
    setPairHistory(null);
    fleetPanel.setOpen(true);
  }
  // View Logs on the connector whose history is open closes it.
  function togglePairHistory(row: IndexingConnectorRow) {
    adminPicked.current = true;
    setPairHistory((open) =>
      open?.cc_pair_id === row.cc_pair_id ? null : row
    );
    setRange(null);
  }
  // Hiding from the panel button drops a pair's history and the span too, so the button reopens the fleet.
  function setHistoryOpen(open: boolean) {
    if (open) {
      showFleetHistory();
      return;
    }
    setPairHistory(null);
    fleetPanel.setOpen(false);
    setRange(null);
  }
  // A failure line focuses its card in the fleet's history, so the history opens.
  const activityLinks = useActivityChartLinks({
    onFocusAttempt: showFleetHistory,
  });
  // A connector's open popover steps the overview back with the other connectors.
  const [listFocused, setListFocused] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  // What the history shows: the fleet over a span, or one connector. A new subject brings the panel into view.
  const subject =
    history === null
      ? null
      : history === "fleet"
        ? `fleet ${range?.since ?? ""} ${range?.until ?? ""}`
        : `pair ${history.cc_pair_id}`;
  useEffect(() => {
    if (subject !== null && adminPicked.current) {
      revealHistory(panelRef.current);
    }
  }, [subject]);

  return (
    <SettingsLayouts.Root width="xl" narrowGutters>
      <SettingsLayouts.Header
        icon={route.icon}
        title={t("title")}
        divider
        actions={
          canAddConnector
            ? [
                // The catalog page is where a connector is added.
                <Button
                  key="add"
                  icon={SvgPlus}
                  href={ADMIN_ROUTES.CONNECTORS.path}
                >
                  {t("addConnector")}
                </Button>,
              ]
            : undefined
        }
      />
      <PanelPageBody
        panel={
          history === "fleet" ? (
            <ActivityPanel
              scope="fleet"
              title={t("activities.panel.title")}
              range={range}
              onClearRange={() => setRange(null)}
              {...activityLinks.panel}
              sticky
              ref={panelRef}
            />
          ) : (
            history !== null && (
              <PairActivityPanel
                key={history.cc_pair_id}
                row={history}
                onClose={() => setPairHistory(null)}
                onHoverPair={activityLinks.panel.onHoverPair}
                ref={panelRef}
              />
            )
          )
        }
      >
        <OverviewCard
          range={range}
          onRangeChange={(picked) => {
            setRange(picked);
            if (picked !== null) showFleetHistory();
          }}
          activityLinks={activityLinks.chart}
          panelOpen={historyOpen}
          onPanelOpenChange={setHistoryOpen}
          className={focusDimClass(listFocused)}
        />
        <ConnectorList
          onViewLogs={togglePairHistory}
          onFocusChange={setListFocused}
          liftedCcPairId={historyOpen ? activityLinks.liftedPairId : null}
        />
        <StackedPanelToggle open={historyOpen} onOpenChange={setHistoryOpen} />
      </PanelPageBody>
    </SettingsLayouts.Root>
  );
}
