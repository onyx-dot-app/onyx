"use client";

import type { Route } from "next";
import { useNavigation, useSearchParams } from "@opal/navigation";
import {
  use,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { useTranslations } from "next-intl";
import useSWR, { mutate } from "swr";
import {
  Button,
  Divider,
  Dropdown,
  MessageCard,
  Tabs,
  Text,
  type DropdownMenuItem,
  useCreateModal,
} from "@opal/components";
import {
  Content,
  IllustrationContent,
  PageCenter,
  Section,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { CardLoader, IconLoader } from "@opal/loaders";
import { markdown } from "@opal/utils";
import { SvgPlugBroken } from "@opal/illustrations";
import {
  SvgArrowLeft,
  SvgEditBig,
  SvgPause,
  SvgPlay,
  SvgPlayCircle,
  SvgRefreshCw,
  SvgSettings,
  SvgSlowMotion,
  SvgTrash,
  SvgUserSync,
} from "@opal/icons";
import { isPermSynced } from "@/lib/connectors/accessType";
import { isEditableSource } from "@/lib/connectors/edit/editable";
import { getCredentialSpec } from "@/lib/credentials/utils";
import { updateConnectorCredentialPairName } from "@/lib/connector";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import {
  releaseIndexingHold,
  triggerIndexing,
  triggerPermissionSync,
} from "@/lib/connectors/svc";
import {
  ConnectorCredentialPairStatus,
  PermissionSyncStatusEnum,
  type CCPairRunKind,
} from "@/lib/connectors/types";
import type { CCPairFullInfo } from "@/lib/connectors/types";
import { statusIsNotCurrentlyActive } from "@/lib/connectors/utils";
import { deleteCCPair } from "@/lib/documentDeletion";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";
import {
  CC_PAIR_STATUS_POLL_MS,
  useActivityChartLinks,
  useActivityPanelOpen,
  useLatestCCPairRun,
  useStatusChange,
} from "@/lib/connectors/ccPair/hooks";
import { can } from "@/lib/permissions/resource-actions";
import { getSourceMetadata } from "@/lib/connectors/utils";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import PendingBackfills from "@/views/admin/connectors/ConnectorDetailPage/PendingBackfills";
import StatusCard from "@/views/admin/connectors/ConnectorDetailPage/StatusCard";
import PairChecksCard from "@/views/admin/connectors/ConnectorDetailPage/PairChecksCard";
import AuthenticationAccountSection from "@/views/admin/connectors/ConnectorDetailPage/AuthenticationAccountSection";
import IndexConfigurationsSection from "@/views/admin/connectors/ConnectorDetailPage/IndexConfigurationsSection";
import SharingSettingsSection from "@/views/admin/connectors/ConnectorDetailPage/SharingSettingsSection";
import ScheduleSection from "@/views/admin/connectors/ConnectorDetailPage/ScheduleSection";
import IndexingTab from "@/views/admin/connectors/ConnectorDetailPage/IndexingTab";
import {
  parseRunParams,
  writeRunParams,
  type RunRef,
} from "@/views/admin/connectors/ConnectorDetailPage/runLink";
import ActivityPanel from "@/views/admin/connectors/ConnectorDetailPage/ActivityPanel";
import PanelPageBody, {
  BESIDE,
} from "@/views/admin/connectors/shared/PanelPageBody";
import { useAdminTopBar } from "@/layouts/chromes/AdminTopBarSlot";
import {
  DEFAULT_PAIR_WINDOW,
  pickWindow,
  type PickerWindow,
  type PickedWindow,
  type SliceRange,
} from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";

type ConnectorTab = "configurations" | "indexing";

function parseTab(value: string | null): ConnectorTab {
  return value === "indexing" ? "indexing" : "configurations";
}

/** The pair has an index attempt under the current model or documents from an earlier one. The attempt count covers only the current search settings, so a model swap would otherwise read as never indexed. */
function hasIndexed(ccPair: CCPairFullInfo): boolean {
  return ccPair.number_of_index_attempts > 0 || ccPair.num_docs_indexed > 0;
}

/** The pair has indexed, queued a permission sync, or has a group sync run in any state, so the Indexing tab has a run to show. A group sync can start before the first index, and the pair records only its successes. */
function hasStartedARun(
  ccPair: CCPairFullInfo,
  hasGroupSyncRun: boolean
): boolean {
  return (
    hasIndexed(ccPair) ||
    ccPair.last_permission_sync_attempt_status !== null ||
    ccPair.last_time_external_group_sync !== null ||
    hasGroupSyncRun
  );
}

function Main({ ccPairId }: { ccPairId: number }) {
  const t = useTranslations("admin.connector");
  const tActivities = useTranslations("admin.indexing.activities");
  const navigation = useNavigation();
  const searchParams = useSearchParams();
  const [pickedTab, setPickedTab] = useState<ConnectorTab>(() =>
    parseTab(searchParams.get("tab"))
  );
  // A new object per click, so the same hint opens its run again.
  const [openRun, setOpenRun] = useState<RunRef | null>(() =>
    parseRunParams(searchParams)
  );
  // Only the pair's id keys the admin's choice and the default count.
  const activityPanel = useActivityPanelOpen({
    ccPairId,
    canResolve: false,
    canResolveRuns: false,
  });
  const panelRef = useRef<HTMLDivElement>(null);
  // Counts View Errors clicks with no index run to focus, each of which resets the panel's filters and scrolls it into view.
  const [errorsRequest, setErrorsRequest] = useState(0);
  // Stacked under the column, the panel is out of view, so it scrolls there.
  useEffect(() => {
    if (errorsRequest > 0) {
      panelRef.current?.scrollIntoView({
        block: "nearest",
        behavior: "smooth",
      });
    }
  }, [errorsRequest]);

  const {
    data: ccPair,
    isLoading: isLoadingCCPair,
    error: ccPairError,
  } = useSWR<CCPairFullInfo>(
    buildCCPairInfoUrl(ccPairId),
    errorHandlingFetcher,
    { refreshInterval: CC_PAIR_STATUS_POLL_MS }
  );
  // The status card reads the same feed, so this shares its request.
  const { data: groupSyncRuns } = useLatestCCPairRun(
    ccPairId,
    "group_sync",
    ccPair !== undefined && isPermSynced(ccPair.access_type),
    CC_PAIR_STATUS_POLL_MS
  );

  const {
    handleStatusChange,
    isUpdating: isStatusUpdating,
    ConfirmModal,
  } = useStatusChange(ccPair || null);

  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  // A Manage menu action in flight: the Manage button spins meanwhile.
  const [busy, setBusy] = useState(false);
  const deleteConnectorModal = useCreateModal();
  // Counts the status card's asks to open the checks card.
  const [checksExpandRequest, setChecksExpandRequest] = useState(0);
  // One window drives the Indexing tab's chart and run list.
  const [timeWindow, setTimeWindow] = useState<PickedWindow>(() =>
    pickWindow(DEFAULT_PAIR_WINDOW)
  );
  // A picked span of the chart brushes it and narrows the runs and activity to it.
  const [sliceRange, setSliceRange] = useState<SliceRange | null>(null);
  function showTab(next: ConnectorTab) {
    setPickedTab(next);
    // The span's only clear control is the chart's picker, which leaves with the Indexing tab.
    if (next !== "indexing") setSliceRange(null);
  }
  // A same-page link, such as a resolved error's later run, or Back changes the address without remounting the page.
  const linkedTab = searchParams.get("tab");
  const linkedRun = parseRunParams(searchParams);
  const linkedRunId = linkedRun?.id ?? null;
  const linkedRunKind = linkedRun?.kind ?? null;
  useEffect(() => {
    showTab(parseTab(linkedTab));
    if (linkedRunId === null || linkedRunKind === null) {
      setOpenRun(null);
      return;
    }
    // The address also echoes the page's own picks, which already hold this run.
    setOpenRun((current) =>
      current?.id === linkedRunId && current.kind === linkedRunKind
        ? current
        : { id: linkedRunId, kind: linkedRunKind }
    );
  }, [linkedTab, linkedRunId, linkedRunKind]);
  // A failure line or the Indexing card's View Errors focuses a card in the panel, so the panel shows.
  const activityLinks = useActivityChartLinks({
    onFocusAttempt: () => activityPanel.setOpen(true),
  });
  const clearRange = () => setSliceRange(null);
  // The span belongs to the old chart, so a new window drops it.
  const changeWindow = (picked: PickerWindow) => {
    setTimeWindow(pickWindow(picked));
    setSliceRange(null);
  };
  // A shallow replace keeps the tab across a reload without a router navigation, which would refetch the page's data.
  const selectTab = (next: ConnectorTab, run: RunRef | null = null) => {
    showTab(next);
    setOpenRun(run);
    const query = new URLSearchParams(searchParams.toString());
    query.set("tab", next);
    writeRunParams(query, run);
    // SAFETY: a query-only href keeps this page's path.
    navigation.go(`?${query.toString()}` as Route, {
      replace: true,
      shallow: true,
    });
  };
  const showRun = (id: number, kind: CCPairRunKind) =>
    selectTab("indexing", { id, kind });
  // A chart span can exclude the clicked errors, so focusing them drops it. Only an index run's card can take the focus.
  const focusErrors = (attemptId: number | null) => {
    setSliceRange(null);
    if (attemptId !== null) {
      activityLinks.focusAttempt(attemptId);
      return;
    }
    activityPanel.setOpen(true);
    setErrorsRequest((n) => n + 1);
  };
  const isSchedulingConnectorDeletionRef = useRef(false);

  const refresh = useCallback(() => {
    mutate(buildCCPairInfoUrl(ccPairId));
  }, [ccPairId]);

  const finishConnectorDeletion = useCallback(() => {
    navigation.go(ADMIN_ROUTES.INDEXING_STATUS.path);
  }, [navigation]);

  const scheduleConnectorDeletion = useCallback(() => {
    if (!ccPair) return;
    if (isSchedulingConnectorDeletionRef.current) return;
    isSchedulingConnectorDeletionRef.current = true;

    deleteCCPair(ccPair.connector.id, ccPair.credential.id).catch((error) => {
      toast.error(
        t("toasts.deletionScheduleFailed", { message: error.message })
      );
    });
    finishConnectorDeletion();
  }, [ccPair, finishConnectorDeletion, t]);

  const triggerReIndex = async (fromBeginning: boolean) => {
    if (!ccPair) return;
    setBusy(true);
    try {
      const result = await triggerIndexing(
        fromBeginning,
        ccPair.connector.id,
        ccPair.credential.id,
        ccPair.id
      );
      if (result.success) {
        toast.success(
          fromBeginning
            ? t("toasts.completeReindexStarted")
            : t("toasts.indexingUpdateStarted")
        );
      } else {
        toast.error(result.message || t("toasts.indexingStartFailed"));
      }
    } catch (error) {
      console.error("Failed to trigger indexing:", error);
      toast.error(t("toasts.indexingStartUnexpectedError"));
    } finally {
      setBusy(false);
    }
  };

  const startIndexing = async () => {
    if (!ccPair) return;
    setBusy(true);
    const failure = await releaseIndexingHold(
      ccPair.id,
      t("statusCard.hold.releaseFailed")
    );
    setBusy(false);
    if (failure !== null) {
      toast.error(failure);
      return;
    }
    toast.success(t("statusCard.hold.released"));
    refresh();
  };

  const syncPermissions = async () => {
    if (!ccPair) return;
    setBusy(true);
    const failure = await triggerPermissionSync(
      ccPair.id,
      t("toasts.permissionSyncFailed")
    );
    setBusy(false);
    if (failure !== null) {
      toast.error(failure);
      return;
    }
    toast.success(t("toasts.permissionSyncStarted"));
    refresh();
  };

  useEffect(() => {
    if (isLoadingCCPair) return;
    if (ccPair && !ccPairError) setHasLoadedOnce(true);

    // Redirect only when the cc-pair is genuinely gone, a real 404 (deleted)
    // or DELETING state, never on a transient poll error.
    if (
      (hasLoadedOnce && ccPairError?.status === 404) ||
      (ccPair?.status === ConnectorCredentialPairStatus.DELETING &&
        !ccPair.connector)
    ) {
      finishConnectorDeletion();
    }
  }, [
    isLoadingCCPair,
    ccPair,
    ccPairError,
    hasLoadedOnce,
    finishConnectorDeletion,
  ]);

  const handleUpdateName = async (newName: string) => {
    if (!ccPair || !newName) return;
    try {
      const response = await updateConnectorCredentialPairName(
        ccPair.id,
        newName
      );
      if (!response.ok) throw new Error(await response.text());
      mutate(buildCCPairInfoUrl(ccPairId));
    } catch {
      toast.error(t("toasts.nameUpdateFailed"));
    }
  };

  if (isLoadingCCPair) {
    return (
      <SettingsLayouts.Root width="xl" narrowGutters>
        <BackToConnectors />
        <PanelPageBody>
          <ConnectorTabs
            value="configurations"
            onValueChange={selectTab}
            loading
          />
          <CardLoader descriptionLines={2} />
        </PanelPageBody>
      </SettingsLayouts.Root>
    );
  }

  if (!ccPair || (!hasLoadedOnce && ccPairError)) {
    const title = t("loadError.title", { ccPairId: String(ccPairId) });
    return (
      <SettingsLayouts.Root width="sm">
        <BackToConnectors />
        <SettingsLayouts.Body>
          <PageCenter>
            <IllustrationContent
              illustration={SvgPlugBroken}
              title={title}
              description={
                ccPairError?.info?.detail ||
                ccPairError?.toString() ||
                t("loadError.unknownMessage")
              }
            />
          </PageCenter>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  const isDeleting = ccPair.status === ConnectorCredentialPairStatus.DELETING;
  const source = ccPair.connector.source;
  const canOperate = can(ccPair, "operate");
  const paused = statusIsNotCurrentlyActive(ccPair.status);
  const canOpenEditForm =
    !isDeleting && can(ccPair, "edit") && isEditableSource(source);
  const openEditForm = () =>
    navigation.go(`/admin/connectors/${source}/edit/${ccPair.id}`);
  const onEdit = canOpenEditForm ? openEditForm : null;
  const canManageInlineFiles = source === "file" && can(ccPair, "edit");
  // A credential-less source's pair holds a placeholder credential with no account or checks.
  const takesCredential = getCredentialSpec(source) !== null;

  // Unlike `paused`, this excludes INVALID, whose menu still offers the re-index rows, disabled with a reason, once it has indexed.
  const strictlyPaused = ccPair.status === ConnectorCredentialPairStatus.PAUSED;
  const held = ccPair.indexing_hold;
  const runStarted = hasStartedARun(
    ccPair,
    (groupSyncRuns?.total_items ?? 0) > 0
  );
  // A disabled Indexing tab shows Configurations but keeps the pick, so the poll that enables it opens the tab the URL asked for.
  const tab = runStarted ? pickedTab : "configurations";
  // While held, the menu offers Start Indexing in place of the re-index rows; a check run in flight releases the hold itself.
  const canStartIndexing = held !== null && held.reason !== "checks_running";
  // The reason a row is disabled is its tooltip.
  const reIndexBlocked = ccPair.indexing
    ? t("manageMenu.reIndex.tooltip.indexing")
    : ccPair.status === ConnectorCredentialPairStatus.INVALID
      ? t("manageMenu.reIndex.tooltip.invalid")
      : undefined;
  const startItems: DropdownMenuItem[] = canStartIndexing
    ? [
        {
          kind: "action",
          id: "start-indexing",
          icon: SvgPlay,
          title: t("manageMenu.startIndexing.label"),
          description: t("manageMenu.startIndexing.description"),
          disabled: busy,
          onSelect: () => void startIndexing(),
        },
      ]
    : [];
  // The first index is already on its way, so there is nothing to update or re-index before it starts.
  const reIndexable = held === null && hasIndexed(ccPair);
  const reIndexItems = (full: boolean): DropdownMenuItem[] =>
    reIndexable
      ? [
          {
            kind: "action",
            id: full ? "full-reindex" : "update-index",
            icon: full ? SvgSlowMotion : SvgRefreshCw,
            title: full
              ? t("manageMenu.fullReindex.label")
              : t("manageMenu.updateIndex.label"),
            description: full
              ? markdown(t("manageMenu.fullReindex.description"))
              : t("manageMenu.updateIndex.description"),
            tooltip: reIndexBlocked,
            disabled: reIndexBlocked !== undefined,
            onSelect: () => void triggerReIndex(full),
          },
        ]
      : [];
  // The route refuses a second sync while one is queued or running.
  const syncOpen =
    ccPair.permission_syncing ||
    ccPair.last_permission_sync_attempt_status ===
      PermissionSyncStatusEnum.NOT_STARTED;
  // Only a source with document permission sync gets the row, and a deleting pair's sync is refused.
  const syncItems: DropdownMenuItem[] =
    isPermSynced(ccPair.access_type) &&
    ccPair.supports_doc_permission_sync &&
    !isDeleting
      ? [
          {
            kind: "action",
            id: "sync-permissions",
            icon: SvgUserSync,
            title: t("manageMenu.syncPermissions.label"),
            description: t("manageMenu.syncPermissions.description"),
            tooltip: syncOpen
              ? t("manageMenu.syncPermissions.tooltip.syncing")
              : undefined,
            disabled: busy || syncOpen,
            onSelect: () => void syncPermissions(),
          },
        ]
      : [];
  const toggleItems: DropdownMenuItem[] = isDeleting
    ? []
    : [
        {
          kind: "action",
          id: "toggle-status",
          icon: paused ? SvgPlayCircle : SvgPause,
          title: paused
            ? t("manageMenu.toggleStatus.resume.label")
            : t("manageMenu.toggleStatus.pause.label"),
          description: paused
            ? t("manageMenu.toggleStatus.resume.description")
            : t("manageMenu.toggleStatus.pause.description"),
          tooltip: isStatusUpdating
            ? t("manageMenu.toggleStatus.tooltip.updating")
            : undefined,
          disabled: isStatusUpdating,
          onSelect: () =>
            handleStatusChange(
              paused
                ? ConnectorCredentialPairStatus.ACTIVE
                : ConnectorCredentialPairStatus.PAUSED
            ),
        },
      ];
  // An untitled group, so the list draws its divider above the danger row.
  const dangerItems: DropdownMenuItem[] =
    !isDeleting && can(ccPair, "delete")
      ? [
          {
            kind: "group",
            items: [
              {
                kind: "action",
                id: "delete",
                icon: SvgTrash,
                danger: true,
                title: t("manageMenu.delete.label"),
                description: t("manageMenu.delete.description"),
                onSelect: () => deleteConnectorModal.toggle(true),
              },
            ],
          },
        ]
      : [];
  const manageItems: DropdownMenuItem[] = strictlyPaused
    ? [...toggleItems, ...dangerItems]
    : [
        ...startItems,
        ...reIndexItems(false),
        ...syncItems,
        ...reIndexItems(true),
        ...toggleItems,
        ...dangerItems,
      ];

  return (
    <SettingsLayouts.Root width="xl" narrowGutters>
      {ConfirmModal}
      <deleteConnectorModal.Provider>
        <ConfirmEntityModal
          danger
          entityType={t("deleteModal.entityType")}
          entityName={ccPair.name}
          additionalDetails={t("deleteModal.additionalDetails")}
          onClose={() => deleteConnectorModal.toggle(false)}
          onSubmit={scheduleConnectorDeletion}
        />
      </deleteConnectorModal.Provider>

      <BackToConnectors />
      <SettingsLayouts.Header
        icon={getSourceMetadata(source).icon}
        title={ccPair.name}
        editable={canOperate}
        editButton="rest"
        onTitleChange={(name) => void handleUpdateName(name)}
        divider
        actions={
          canOperate
            ? [
                ...(canOpenEditForm
                  ? [
                      <Button
                        key="edit"
                        prominence="secondary"
                        icon={SvgEditBig}
                        onClick={openEditForm}
                      >
                        {t("configuration.editButton.label")}
                      </Button>,
                    ]
                  : []),
                <Dropdown key="manage" width={80} align="end">
                  <Dropdown.Trigger asChild>
                    <Button
                      prominence="secondary"
                      icon={busy || isStatusUpdating ? IconLoader : SvgSettings}
                    >
                      {t("manageMenu.trigger.label")}
                    </Button>
                  </Dropdown.Trigger>
                  {/* The mock sizes the menu to its rows. */}
                  <Dropdown.Data
                    label={t("manageMenu.trigger.label")}
                    items={manageItems}
                    maxHeight="none"
                  />
                </Dropdown>,
              ]
            : undefined
        }
      />

      <PanelPageBody
        panel={
          <ActivityPanel
            scope={{
              ccPairId: ccPair.id,
              canResolve: canOperate && ccPair.supports_targeted_reindex,
              canResolveRuns: canOperate,
            }}
            title={tActivities("title")}
            range={sliceRange}
            onClearRange={clearRange}
            {...activityLinks.panel}
            errorsRequest={errorsRequest}
            className={activityPanel.open ? undefined : BESIDE.panelHidden}
            ref={panelRef}
          />
        }
      >
        {ccPair.deletion_failure_message && isDeleting && (
          <MessageCard
            variant="error"
            title={t("deletionError.title")}
            description={t("deletionError.description")}
            bottomChildren={
              <Text font="secondary-body" color="text-04">
                {ccPair.deletion_failure_message}
              </Text>
            }
          />
        )}
        {ccPair.status === ConnectorCredentialPairStatus.INVALID && (
          <MessageCard
            variant="warning"
            title={t("invalidState.title")}
            description={t("invalidState.description")}
          />
        )}
        {ccPair.pending_backfills.length > 0 && (
          <PendingBackfills backfills={ccPair.pending_backfills} />
        )}

        <StatusCard
          ccPair={ccPair}
          onStartIndexing={canOperate ? () => void startIndexing() : null}
          startingIndexing={busy}
          onViewChecks={() => setChecksExpandRequest((n) => n + 1)}
          onOpenRun={showRun}
          onFocusErrors={focusErrors}
          panelOpen={activityPanel.open}
          onTogglePanel={() => activityPanel.setOpen(!activityPanel.open)}
          panelButtonClassName={BESIDE.hiddenStacked}
        />
        {takesCredential && (
          <PairChecksCard
            source={source}
            credentialId={ccPair.credential.id}
            connectorId={ccPair.connector.id}
            held={ccPair.indexing_hold !== null}
            expandRequest={checksExpandRequest}
          />
        )}
        <Divider paddingParallel={0} paddingPerpendicular={0} />

        <ConnectorTabs
          value={tab}
          onValueChange={selectTab}
          indexingDisabled={!runStarted}
        >
          {/* Kept mounted so an inline edit survives a look at the Indexing tab. */}
          <Tabs.Content value="configurations" keepMounted>
            <Section alignItems="stretch" gap={6} height="fit">
              {takesCredential && (
                <AuthenticationAccountSection ccPair={ccPair} onEdit={onEdit} />
              )}
              <IndexConfigurationsSection
                ccPair={ccPair}
                onEdit={onEdit}
                manageFiles={canManageInlineFiles}
                onRefresh={refresh}
              />
              <SharingSettingsSection ccPair={ccPair} onEdit={onEdit} />
              <Divider paddingParallel={0} paddingPerpendicular={0} />
              <ScheduleSection ccPair={ccPair} editable={canOperate} />
            </Section>
          </Tabs.Content>
          <Tabs.Content value="indexing">
            <IndexingTab
              ccPairId={ccPair.id}
              canOperate={canOperate}
              timeWindow={timeWindow}
              onTimeWindowChange={changeWindow}
              range={sliceRange}
              onRangeChange={setSliceRange}
              activityLinks={activityLinks.chart}
              liftedAttemptId={
                activityLinks.chart.hoveredAttemptId ??
                activityLinks.panel.focusAttemptId
              }
              openRun={openRun}
            />
          </Tabs.Content>
        </ConnectorTabs>
      </PanelPageBody>
    </SettingsLayouts.Root>
  );
}

interface ConnectorTabsProps {
  value: ConnectorTab;
  onValueChange: (tab: ConnectorTab) => void;
  /** Both tabs wait for the pair. */
  loading?: boolean;
  indexingDisabled?: boolean;
  children?: ReactNode;
}

function ConnectorTabs({
  value,
  onValueChange,
  loading = false,
  indexingDisabled = false,
  children,
}: ConnectorTabsProps) {
  const t = useTranslations("admin.connector.tabs");
  return (
    <Tabs
      value={value}
      onValueChange={(next) => onValueChange(parseTab(next))}
      gap={6}
    >
      <Tabs.List>
        <Tabs.Trigger value="configurations" disabled={loading}>
          {t("configurations")}
        </Tabs.Trigger>
        <Tabs.Trigger
          value="indexing"
          disabled={loading || indexingDisabled}
          tooltip={
            !loading && indexingDisabled ? t("indexingDisabled") : undefined
          }
        >
          {t("indexing")}
        </Tabs.Trigger>
      </Tabs.List>
      {children}
    </Tabs>
  );
}

/** The back link, in the admin top bar beside the sidebar button while there is one. */
function BackToConnectors() {
  const t = useTranslations("admin.connector");
  const navigation = useNavigation();
  const topBar = useAdminTopBar();
  const link = (
    <Button
      icon={SvgArrowLeft}
      prominence="tertiary"
      size="md"
      {...navigation.linkTo(ADMIN_ROUTES.INDEXING_STATUS.path)}
    >
      {t("backButton.label")}
    </Button>
  );
  if (topBar !== null) return createPortal(link, topBar);
  return (
    // Section's padding is inline, so the narrow gutter comes off the margin: 16 px, then 8 below 816 px of page.
    <Section
      alignItems="start"
      width="auto"
      height="fit"
      padding={2}
      className="m-2 @max-[51rem]/settings-page:mx-0"
    >
      {link}
    </Section>
  );
}

export default function Page(props: { params: Promise<{ ccPairId: string }> }) {
  const params = use(props.params);
  return <Main ccPairId={parseInt(params.ccPairId)} />;
}
