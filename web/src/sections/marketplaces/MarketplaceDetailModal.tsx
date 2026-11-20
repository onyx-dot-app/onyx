"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, MessageCard, Modal, Text } from "@opal/components";
import { Content, KeyValue, Section, toast } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgBlocks, SvgRefreshCw } from "@opal/icons";
import { SvgGitHub } from "@opal/logos";
import { fetchErrorDetail } from "@/lib/fetcher";
import {
  confirmMarketplaceDeletes,
  syncMarketplace,
} from "@/lib/marketplaces/api";
import { useMarketplace } from "@/lib/marketplaces/hooks";
import type { MarketplaceDetail } from "@/lib/marketplaces/types";
import { marketplaceSyncState } from "@/lib/marketplaces/utils";
import {
  useInstallationPolicyCopy,
  useRefreshSkillLists,
} from "@/lib/skills/hooks";
import { ENTRY_STATUS_COLOR } from "@/sections/marketplaces/MarketplacePreview";
import MarketplaceSyncStatus, {
  useLastSyncCopy,
} from "@/sections/marketplaces/MarketplaceSyncStatus";

interface DetailBodyProps {
  marketplace: MarketplaceDetail;
  busy: boolean;
  onConfirmDeletes: (revision: string) => void;
}

function DetailBody({ marketplace, busy, onConfirmDeletes }: DetailBodyProps) {
  const t = useTranslations("plugins.marketplaces");
  const lastSync = useLastSyncCopy();
  const policyCopy = useInstallationPolicyCopy();
  const revision = marketplace.pending_delete_revision;
  return (
    <Section gap={4} alignItems="stretch" height="auto">
      <MarketplaceSyncStatus marketplace={marketplace} />
      {revision && marketplace.pending_deletes.length > 0 && (
        <MessageCard
          variant="warning"
          outerPadding={1}
          innerPadding={1}
          title={t("pendingDeletes.title", {
            count: marketplace.pending_deletes.length,
          })}
          description={t("pendingDeletes.description")}
          bottomChildren={
            <Section gap={2} alignItems="stretch" height="auto">
              <Section
                role="list"
                aria-label={t("pendingDeletes.listLabel")}
                gap={1}
                alignItems="stretch"
                height="auto"
              >
                {marketplace.pending_deletes.map((plugin) => (
                  <Section
                    key={plugin.plugin_id}
                    role="listitem"
                    alignItems="stretch"
                    height="auto"
                  >
                    <Content
                      font="main-ui-body"
                      icon={SvgBlocks}
                      title={plugin.name}
                    />
                  </Section>
                ))}
              </Section>
              <Section flexDirection="row" justifyContent="end" height="auto">
                <Button
                  variant="danger"
                  size="sm"
                  disabled={busy}
                  onClick={() => onConfirmDeletes(revision)}
                >
                  {t("pendingDeletes.confirm", {
                    count: marketplace.pending_deletes.length,
                  })}
                </Button>
              </Section>
            </Section>
          }
        />
      )}
      {marketplace.last_error && (
        <MessageCard
          variant="error"
          outerPadding={1}
          innerPadding={1}
          title={t("attention.failedTitle", { name: marketplace.name })}
          description={marketplace.last_error}
        />
      )}
      <Card padding={4} border="solid">
        <Section gap={3} alignItems="stretch" height="auto">
          <KeyValue
            label={t("source.repository")}
            value={marketplace.repository}
            mono
          />
          <KeyValue
            label={t("source.folder")}
            value={marketplace.folder ?? t("source.root")}
            mono={marketplace.folder !== null}
          />
          <KeyValue
            label={t("source.ref")}
            value={marketplace.ref ?? t("source.defaultBranch")}
            mono={marketplace.ref !== null}
          />
          {marketplace.last_synced_revision && (
            <KeyValue
              label={t("source.commit")}
              value={marketplace.last_synced_revision.slice(0, 12)}
              mono
            />
          )}
          <KeyValue
            label={t("detail.scope")}
            value={t(`scope.${marketplace.scope}`)}
          />
          {marketplace.scope === "company" && (
            <KeyValue
              label={t("defaultAccess.title")}
              value={policyCopy.label(marketplace.default_installation_policy)}
            />
          )}
          <KeyValue
            label={t("detail.login")}
            value={marketplace.login_user?.email ?? t("detail.noLogin")}
          />
          <KeyValue
            label={t("detail.lastSync")}
            value={lastSync(marketplace)}
          />
        </Section>
      </Card>
      <Section gap={2} alignItems="stretch" height="auto">
        <Text as="p" font="main-ui-action" color="text-04">
          {t("detail.entries", { count: marketplace.entries.length })}
        </Text>
        {marketplace.entries.length === 0 ? (
          <Text as="p" font="secondary-body" color="text-03">
            {t("detail.noEntries")}
          </Text>
        ) : (
          marketplace.entries.map((entry) => (
            <Card key={entry.key} padding={2} border="solid">
              <Content
                icon={SvgBlocks}
                title={entry.plugin_name ?? entry.key}
                description={entry.reason ?? entry.path ?? undefined}
                badge={{
                  title: t(`status.${entry.status}`),
                  color: ENTRY_STATUS_COLOR[entry.status],
                }}
              />
            </Card>
          ))
        )}
      </Section>
    </Section>
  );
}

interface MarketplaceDetailModalProps {
  marketplaceId: string;
  onClose: () => void;
  /** Called after a change, so the host list reads again. */
  onChanged: () => void;
}

export default function MarketplaceDetailModal({
  marketplaceId,
  onClose,
  onChanged,
}: MarketplaceDetailModalProps) {
  const t = useTranslations("plugins.marketplaces");
  const { marketplace, error, refresh, follow } = useMarketplace(marketplaceId);
  const refreshSkillLists = useRefreshSkillLists();
  const [busy, setBusy] = useState(false);

  async function run(
    call: () => Promise<MarketplaceDetail>,
    success: string,
    failure: string
  ) {
    setBusy(true);
    try {
      await refresh(await call(), { revalidate: false });
      follow();
      onChanged();
      refreshSkillLists();
      toast.success(success);
    } catch (caught) {
      toast.error(fetchErrorDetail(caught) ?? failure);
      void refresh();
    } finally {
      setBusy(false);
    }
  }

  const name = marketplace?.name ?? "";
  const syncing =
    marketplace !== undefined &&
    marketplaceSyncState(marketplace) === "syncing";

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && !busy && onClose()}>
      <Modal.Content width="md" maxHeight="85dvh">
        <Modal.Header
          icon={SvgGitHub}
          title={marketplace?.name ?? t("detail.title")}
          description={t("detail.description")}
          onClose={busy ? undefined : onClose}
        />
        <Modal.Body padding={2}>
          {error ? (
            <MessageCard
              variant="error"
              outerPadding={1}
              innerPadding={1}
              title={t("detail.loadFailed")}
              description={fetchErrorDetail(error) ?? undefined}
            />
          ) : !marketplace ? (
            <Section height="auto" className="min-h-20">
              <IconLoader />
            </Section>
          ) : (
            <DetailBody
              marketplace={marketplace}
              busy={busy}
              onConfirmDeletes={(revision) =>
                void run(
                  () => confirmMarketplaceDeletes(marketplaceId, revision),
                  t("pendingDeletes.done"),
                  t("pendingDeletes.failed")
                )
              }
            />
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" disabled={busy} onClick={onClose}>
            {t("detail.close")}
          </Button>
          {marketplace && (
            <Button
              icon={SvgRefreshCw}
              disabled={busy || syncing}
              onClick={() =>
                void run(
                  () => syncMarketplace(marketplaceId),
                  t("sync.requested", { name }),
                  t("sync.failed")
                )
              }
            >
              {t("sync.now")}
            </Button>
          )}
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
