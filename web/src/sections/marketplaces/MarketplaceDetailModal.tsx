"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button, Card, MessageCard, Modal, Text } from "@opal/components";
import { Content, KeyValue, Section, toast } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgBlocks, SvgRefreshCw } from "@opal/icons";
import { SvgGitHub } from "@opal/logos";
import { fetchErrorDetail } from "@/lib/fetcher";
import { syncMarketplace } from "@/lib/marketplaces/api";
import { useMarketplace, useMarketplaceCopy } from "@/lib/marketplaces/hooks";
import { sortMarketplaceEntries } from "@/lib/marketplaces/utils";
import type { MarketplaceDetail } from "@/lib/marketplaces/types";
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
}

function DetailBody({ marketplace }: DetailBodyProps) {
  const t = useTranslations("plugins.marketplaces");
  const locale = useLocale();
  const copy = useMarketplaceCopy();
  const lastSync = useLastSyncCopy(false);
  const policyCopy = useInstallationPolicyCopy();
  const limitNote = copy.limitNote(marketplace.entries);
  return (
    <Section gap={4} alignItems="stretch" height="auto">
      <MarketplaceSyncStatus marketplace={marketplace} />
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
          {marketplace.default_installation_policy && (
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
          <>
            {limitNote && (
              <MessageCard
                variant="warning"
                outerPadding={1}
                innerPadding={1}
                title={t("reason.limitTitle")}
                description={limitNote}
              />
            )}
            {sortMarketplaceEntries(marketplace.entries, locale).map(
              (entry) => (
                <Card key={entry.key} padding={2} border="solid">
                  <Content
                    icon={SvgBlocks}
                    title={entry.key}
                    description={
                      copy.entryReason(entry) ?? entry.path ?? undefined
                    }
                    badge={{
                      title: t(`status.${entry.status}`),
                      color: ENTRY_STATUS_COLOR[entry.status],
                    }}
                  />
                </Card>
              )
            )}
          </>
        )}
      </Section>
    </Section>
  );
}

interface MarketplaceDetailModalProps {
  marketplaceId: string;
  onClose: () => void;
  onChanged: () => void;
}

export default function MarketplaceDetailModal({
  marketplaceId,
  onClose,
  onChanged,
}: MarketplaceDetailModalProps) {
  const t = useTranslations("plugins.marketplaces");
  const { marketplace, error, refresh } = useMarketplace(marketplaceId);
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
  const syncing = marketplace?.syncing ?? false;

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
            <DetailBody marketplace={marketplace} />
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" disabled={busy} onClick={onClose}>
            {t("detail.close")}
          </Button>
          {marketplace?.can_manage && (
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
