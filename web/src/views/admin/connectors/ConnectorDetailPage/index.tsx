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
import { SvgPlugBroken } from "@opal/illustrations";
import {
  SvgArrowLeft,
  SvgEdit,
  SvgPauseCircle,
  SvgPlayCircle,
  SvgRefreshCw,
  SvgSettings,
  SvgTrash,
} from "@opal/icons";
import { isEditableSource } from "@/lib/connectors/edit/editable";
import { updateConnectorCredentialPairName } from "@/lib/connector";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import { triggerIndexing } from "@/lib/connectors/svc";
import { ConnectorCredentialPairStatus } from "@/lib/connectors/types";
import type {
  CCPairFullInfo,
  IndexAttemptError,
  PaginatedIndexAttempts,
} from "@/lib/connectors/types";
import { statusIsNotCurrentlyActive } from "@/lib/connectors/utils";
import { deleteCCPair } from "@/lib/documentDeletion";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";
import usePaginatedFetch from "@/hooks/usePaginatedFetch";
import type { IndexAttemptSnapshot } from "@/lib/types";
import { useStatusChange } from "@/lib/connectors/ccPair/hooks";
import { resolveAllErrorsForCCPair } from "@/lib/targeted_reindex";
import { SWR_KEYS } from "@/lib/swr-keys";
import { can } from "@/lib/permissions/resource-actions";
import { isPermSynced } from "@/lib/connectors/accessType";
import { getSourceMetadata } from "@/lib/connectors/utils";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import IndexAttemptErrorsModal from "@/views/admin/connectors/ConnectorDetailPage/IndexAttemptErrorsModal";
import { IndexAttemptsTable } from "@/views/admin/connectors/ConnectorDetailPage/IndexAttemptsTable";
import PendingBackfills from "@/views/admin/connectors/ConnectorDetailPage/PendingBackfills";
import { SyncAttemptsTabs } from "@/views/admin/connectors/ConnectorDetailPage/SyncAttemptsTabs";
import StatusCard from "@/views/admin/connectors/ConnectorDetailPage/StatusCard";
import PairChecksCard from "@/views/admin/connectors/ConnectorDetailPage/PairChecksCard";
import AuthenticationAccountSection from "@/views/admin/connectors/ConnectorDetailPage/AuthenticationAccountSection";
import IndexConfigurationsSection from "@/views/admin/connectors/ConnectorDetailPage/IndexConfigurationsSection";
import SharingSettingsSection from "@/views/admin/connectors/ConnectorDetailPage/SharingSettingsSection";
import ScheduleSection from "@/views/admin/connectors/ConnectorDetailPage/ScheduleSection";

const ITEMS_PER_PAGE = 8;
const PAGES_PER_BATCH = 8;
const CC_PAIR_POLL_MS = 5000;

function Main({ ccPairId }: { ccPairId: number }) {
  const t = useTranslations("admin.connector");
  const editT = useTranslations("admin.connectorEdit");
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
    currentPageData: indexAttempts,
    isLoading: isLoadingIndexAttempts,
    currentPage,
    totalPages,
    goToPage,
  } = usePaginatedFetch<IndexAttemptSnapshot>({
    itemsPerPage: ITEMS_PER_PAGE,
    pagesPerBatch: PAGES_PER_BATCH,
    endpoint: SWR_KEYS.ccPairIndexAttempts(ccPairId),
  });

  // The error notice reads the latest attempt. The status card shares this key.
  const { data: latestIndexAttempts } = useSWR<PaginatedIndexAttempts>(
    SWR_KEYS.ccPairLatestIndexAttempt(ccPairId),
    errorHandlingFetcher,
    { refreshInterval: CC_PAIR_POLL_MS }
  );

  const {
    currentPageData: indexAttemptErrorsPage,
    totalPages: indexAttemptErrorsTotalPages,
    totalItems: indexAttemptErrorsTotalItems,
    currentPage: indexAttemptErrorsCurrentPage,
    goToPage: goToIndexAttemptErrorsPage,
  } = usePaginatedFetch<IndexAttemptError>({
    itemsPerPage: 10,
    pagesPerBatch: 1,
    endpoint: SWR_KEYS.ccPairIndexingErrors(ccPairId),
    disableUrlSync: true,
  });

  const {
    handleStatusChange,
    isUpdating: isStatusUpdating,
    ConfirmModal,
  } = useStatusChange(ccPair || null);

  const indexAttemptErrors = indexAttemptErrorsPage
    ? { items: indexAttemptErrorsPage }
    : null;

  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const [showIndexAttemptErrors, setShowIndexAttemptErrors] = useState(false);
  // A re-index or error resolve in flight: the Manage button spins meanwhile.
  const [busy, setBusy] = useState(false);
  const [showDeleteConnectorConfirmModal, setShowDeleteConnectorConfirmModal] =
    useState(false);
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

  const latestIndexAttempt = latestIndexAttempts?.items[0];
  const isResolvingErrors =
    (latestIndexAttempt?.status === "in_progress" ||
      latestIndexAttempt?.status === "not_started") &&
    latestIndexAttempt?.from_beginning &&
    // Errors in the latest attempt mean it is not the resolving run.
    !indexAttemptErrors?.items?.some(
      (error) => error.index_attempt_id === latestIndexAttempt?.id
    );

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

  if (isLoadingCCPair || isLoadingIndexAttempts) {
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

  // The reason a row is disabled is its tooltip.
  const reIndexBlocked = ccPair.indexing
    ? t("manageMenu.reIndex.tooltip.indexing")
    : ccPair.status === ConnectorCredentialPairStatus.PAUSED
      ? t("manageMenu.reIndex.tooltip.paused")
      : ccPair.status === ConnectorCredentialPairStatus.INVALID
        ? t("manageMenu.reIndex.tooltip.invalid")
        : undefined;
  const manageItems: DropdownMenuItem[] = [
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
      icon: SvgRefreshCw,
      title: t("manageMenu.fullReindex.label"),
      description: t("manageMenu.fullReindex.description"),
      tooltip: reIndexBlocked,
      disabled: reIndexBlocked !== undefined,
      onSelect: () => void triggerReIndex(true),
    },
    ...(!isDeleting
      ? [
          {
            kind: "action" as const,
            id: "toggle-status",
            icon: paused ? SvgPlayCircle : SvgPauseCircle,
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
        ]
      : []),
    ...(!isDeleting && can(ccPair, "delete")
      ? [
          {
            kind: "action" as const,
            id: "delete",
            icon: SvgTrash,
            danger: true,
            title: t("manageMenu.delete.label"),
            tooltip: paused ? undefined : t("manageMenu.delete.tooltip.active"),
            disabled: !paused,
            onSelect: () => setShowDeleteConnectorConfirmModal(true),
          },
        ]
      : []),
  ];

  const resolveAllErrors = async () => {
    setShowIndexAttemptErrors(false);
    if (!ccPair.supports_targeted_reindex) {
      await triggerReIndex(true);
      return;
    }
    setBusy(true);
    try {
      const result = await resolveAllErrorsForCCPair(ccPairId);
      if (result.total_error_ids === 0) {
        toast.success(t("toasts.noUnresolvedErrors"));
      } else {
        toast.success(
          t("toasts.targetedReindexSubmitted", {
            count: result.total_error_ids,
          })
        );
      }
      mutate(
        (key) =>
          typeof key === "string" &&
          key.startsWith(SWR_KEYS.ccPairIndexingErrors(ccPairId))
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(t("toasts.targetedReindexFailed", { message }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SettingsLayouts.Root width="sm">
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
      {showIndexAttemptErrors && indexAttemptErrors && (
        <IndexAttemptErrorsModal
          errors={indexAttemptErrors}
          totalPages={indexAttemptErrorsTotalPages}
          currentPage={indexAttemptErrorsCurrentPage}
          onPageChange={goToIndexAttemptErrorsPage}
          onClose={() => setShowIndexAttemptErrors(false)}
          onResolveAll={resolveAllErrors}
          supportsTargetedReindex={ccPair.supports_targeted_reindex}
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
                        icon={SvgEdit}
                        onClick={openEditForm}
                      >
                        {editT("editButton.label")}
                      </Button>,
                    ]
                  : []),
                <Dropdown key="manage">
                  <Dropdown.Trigger asChild>
                    <Button
                      prominence="secondary"
                      icon={busy || isStatusUpdating ? IconLoader : SvgSettings}
                    >
                      {t("manageMenu.trigger.label")}
                    </Button>
                  </Dropdown.Trigger>
                  <Dropdown.Data
                    label={t("manageMenu.trigger.label")}
                    items={manageItems}
                  />
                </Dropdown>,
              ]
            : undefined
        }
      />

      <SettingsLayouts.Body gap={6}>
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
        {indexAttemptErrors && indexAttemptErrorsTotalItems > 0 && (
          <MessageCard
            variant="warning"
            title={t("indexErrorsAlert.title")}
            description={
              isResolvingErrors
                ? t("indexErrorsAlert.resolvingStatus")
                : t("indexErrorsAlert.description")
            }
            rightChildren={
              !isResolvingErrors && (
                <Button
                  prominence="secondary"
                  onClick={() => setShowIndexAttemptErrors(true)}
                >
                  {t("indexErrorsAlert.detailsButton.label")}
                </Button>
              )
            }
          />
        )}
        {ccPair.pending_backfills.length > 0 && (
          <PendingBackfills backfills={ccPair.pending_backfills} />
        )}

        <StatusCard ccPair={ccPair} />
        <PairChecksCard
          source={source}
          credentialId={ccPair.credential.id}
          connectorId={ccPair.connector.id}
        />
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

        {indexAttempts && (
          <Section alignItems="stretch" gap={3} height="fit">
            <Content
              title={t("runs.title")}
              sizePreset="main-content"
              variant="section"
            />
            {isPermSynced(ccPair.access_type) ? (
              <SyncAttemptsTabs
                ccPair={ccPair}
                indexAttempts={indexAttempts}
                indexCurrentPage={currentPage}
                indexTotalPages={totalPages}
                onIndexPageChange={goToPage}
              />
            ) : (
              <IndexAttemptsTable
                ccPair={ccPair}
                indexAttempts={indexAttempts}
                currentPage={currentPage}
                totalPages={totalPages}
                onPageChange={goToPage}
              />
            )}
          </Section>
        )}
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
