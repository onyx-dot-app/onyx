"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import useSWR, { mutate } from "swr";
import {
  Button,
  Divider,
  Dropdown,
  MessageCard,
  Text,
  type DropdownMenuItem,
} from "@opal/components";
import {
  Content,
  IllustrationContent,
  PageCenter,
  Section,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { IconLoader, PageLoader } from "@opal/loaders";
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
} from "@opal/icons";
import { isEditableSource } from "@/lib/connectors/edit/editable";
import { updateConnectorCredentialPairName } from "@/lib/connector";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import { releaseIndexingHold, triggerIndexing } from "@/lib/connectors/svc";
import { ConnectorCredentialPairStatus } from "@/lib/connectors/types";
import type { CCPairFullInfo } from "@/lib/connectors/types";
import { statusIsNotCurrentlyActive } from "@/lib/connectors/utils";
import { deleteCCPair } from "@/lib/documentDeletion";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";
import { useStatusChange } from "@/lib/connectors/ccPair/hooks";
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
import RunsCard from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";
import ActivityPanel from "@/views/admin/connectors/ConnectorDetailPage/ActivityPanel";
import {
  pickWindow,
  type PickerWindow,
  type PickedWindow,
  type SliceRange,
} from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";
import { focusDimClass } from "@/views/admin/connectors/ConnectorDetailPage/focusMode";

const CC_PAIR_POLL_MS = 5000;

function Main({ ccPairId }: { ccPairId: number }) {
  const t = useTranslations("admin.connector");
  const router = useRouter();

  const {
    data: ccPair,
    isLoading: isLoadingCCPair,
    error: ccPairError,
  } = useSWR<CCPairFullInfo>(
    buildCCPairInfoUrl(ccPairId),
    errorHandlingFetcher,
    { refreshInterval: CC_PAIR_POLL_MS }
  );

  const {
    handleStatusChange,
    isUpdating: isStatusUpdating,
    ConfirmModal,
  } = useStatusChange(ccPair || null);

  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  // A re-index or error resolve in flight: the Manage button spins meanwhile.
  const [busy, setBusy] = useState(false);
  const [showDeleteConnectorConfirmModal, setShowDeleteConnectorConfirmModal] =
    useState(false);
  // Counts the status card's asks to open the checks card.
  const [checksExpandRequest, setChecksExpandRequest] = useState(0);
  const [runFocus, setRunFocus] = useState(false);
  // One window drives the status card's chart and the runs card's list.
  const [timeWindow, setTimeWindow] = useState<PickedWindow>(() =>
    pickWindow("12h")
  );
  // A picked span of the chart zooms it and narrows the runs and activity to it.
  const [sliceRange, setSliceRange] = useState<SliceRange | null>(null);
  // The span belongs to the old chart, so a new window drops it.
  const changeWindow = (picked: PickerWindow) => {
    setTimeWindow(pickWindow(picked));
    setSliceRange(null);
  };
  const isSchedulingConnectorDeletionRef = useRef(false);

  const refresh = useCallback(() => {
    mutate(buildCCPairInfoUrl(ccPairId));
  }, [ccPairId]);

  const finishConnectorDeletion = useCallback(() => {
    router.push(ADMIN_ROUTES.INDEXING_STATUS.path);
  }, [router]);

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
    if (!ccPair) return;
    try {
      const response = await updateConnectorCredentialPairName(
        ccPair.id,
        newName
      );
      if (!response.ok) throw new Error(await response.text());
      mutate(buildCCPairInfoUrl(ccPairId));
      toast.success(t("toasts.nameUpdated"));
    } catch {
      toast.error(t("toasts.nameUpdateFailed"));
    }
  };

  if (isLoadingCCPair) {
    return <PageLoader />;
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
    router.push(`/admin/connectors/${source}/edit/${ccPair.id}`);
  const onEdit = canOpenEditForm ? openEditForm : null;
  const canManageInlineFiles = source === "file" && can(ccPair, "edit");

  // Unlike `paused`, this excludes INVALID, whose menu still offers the re-index rows disabled with a reason.
  const strictlyPaused = ccPair.status === ConnectorCredentialPairStatus.PAUSED;
  const held = ccPair.indexing_hold;
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
  const reIndexItems: DropdownMenuItem[] =
    strictlyPaused || held !== null
      ? []
      : [
          {
            kind: "action",
            id: "update-index",
            icon: SvgRefreshCw,
            title: t("manageMenu.updateIndex.label"),
            description: t("manageMenu.updateIndex.description"),
            tooltip: reIndexBlocked,
            disabled: reIndexBlocked !== undefined,
            onSelect: () => void triggerReIndex(false),
          },
          {
            kind: "action",
            id: "full-reindex",
            icon: SvgSlowMotion,
            title: t("manageMenu.fullReindex.label"),
            description: markdown(t("manageMenu.fullReindex.description")),
            tooltip: reIndexBlocked,
            disabled: reIndexBlocked !== undefined,
            onSelect: () => void triggerReIndex(true),
          },
        ];
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
                tooltip: paused
                  ? undefined
                  : t("manageMenu.delete.tooltip.active"),
                disabled: !paused,
                onSelect: () => setShowDeleteConnectorConfirmModal(true),
              },
            ],
          },
        ]
      : [];
  const manageItems: DropdownMenuItem[] = strictlyPaused
    ? [...toggleItems, ...dangerItems]
    : [...startItems, ...reIndexItems, ...toggleItems, ...dangerItems];

  return (
    <SettingsLayouts.Root width="xl">
      {ConfirmModal}
      {showDeleteConnectorConfirmModal && (
        <ConfirmEntityModal
          danger
          entityType={t("deleteModal.entityType")}
          entityName={ccPair.name}
          additionalDetails={t("deleteModal.additionalDetails")}
          onClose={() => setShowDeleteConnectorConfirmModal(false)}
          onSubmit={scheduleConnectorDeletion}
        />
      )}

      <BackToConnectors />
      <SettingsLayouts.Header
        icon={getSourceMetadata(source).icon}
        title={ccPair.name}
        editable={canOperate}
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

      <SettingsLayouts.Body>
        {/* The panel sits beside the column on wide screens and under it elsewhere. min-w-0 lets the column shrink under long content. */}
        <Section
          flexDirection="row"
          alignItems="start"
          gap={4}
          height="fit"
          className="max-lg:flex-col"
        >
          <Section
            alignItems="stretch"
            gap={6}
            height="fit"
            className="min-w-0 flex-1"
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
              timeWindow={timeWindow.window}
              onTimeWindowChange={changeWindow}
              range={sliceRange}
              onRangeChange={setSliceRange}
            />
            <PairChecksCard
              source={source}
              credentialId={ccPair.credential.id}
              connectorId={ccPair.connector.id}
              expandRequest={checksExpandRequest}
            />
            {/* While a run row's popover is open, the sections step back; the status card stays full. */}
            <Section
              alignItems="stretch"
              gap={6}
              height="fit"
              className={focusDimClass(runFocus)}
            >
              <AuthenticationAccountSection ccPair={ccPair} onEdit={onEdit} />
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

            <RunsCard
              ccPairId={ccPair.id}
              canOperate={canOperate}
              sharedWindow={timeWindow}
              onSharedWindowChange={changeWindow}
              onFocusChange={setRunFocus}
              range={sliceRange}
              onClearRange={() => setSliceRange(null)}
            />
          </Section>
          <ActivityPanel
            scope={{
              ccPairId: ccPair.id,
              canResolve: canOperate && ccPair.supports_targeted_reindex,
              canResolveRuns: canOperate,
            }}
            range={sliceRange}
          />
        </Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

function BackToConnectors() {
  const t = useTranslations("admin.connector");
  return (
    <Section alignItems="start" height="fit" padding={4}>
      <Button
        icon={SvgArrowLeft}
        prominence="tertiary"
        size="md"
        href={ADMIN_ROUTES.INDEXING_STATUS.path}
      >
        {t("backButton.label")}
      </Button>
    </Section>
  );
}

export default function Page(props: { params: Promise<{ ccPairId: string }> }) {
  const params = use(props.params);
  return <Main ccPairId={parseInt(params.ccPairId)} />;
}
