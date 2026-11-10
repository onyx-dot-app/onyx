"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR, { useSWRConfig } from "swr";
import { Button, Modal, Text } from "@opal/components";
import { InputPadder, Section } from "@opal/layouts";
import {
  getMarketplace,
  updateMarketplaceAccess,
} from "@/lib/marketplaces/api";
import {
  marketplaceAccessDraft,
  useCompanyMarketplaceAccess,
} from "@/lib/marketplaces/hooks";
import type { Marketplace } from "@/lib/marketplaces/types";
import { fetchErrorDetail, skipRetryOnAuthError } from "@/lib/fetcher";
import { useSkillLimitFeedback } from "@/lib/skills/hooks";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Permission } from "@/lib/types";
import CompanyMarketplaceAccessControls from "@/sections/marketplaces/CompanyMarketplaceAccessControls";

interface CompanyMarketplaceAccessModalProps {
  marketplaceId: string;
  open: boolean;
  onClose: () => void;
  onSaved?: (marketplace: Marketplace) => void;
}

export default function CompanyMarketplaceAccessModal(
  props: CompanyMarketplaceAccessModalProps
) {
  return props.open ? (
    <AccessSession key={props.marketplaceId} {...props} />
  ) : null;
}

function AccessSession({
  marketplaceId,
  onClose,
  onSaved,
}: CompanyMarketplaceAccessModalProps) {
  const t = useTranslations("marketplaces");
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_SKILLS);
  const sessionId = useId();
  // Each opening needs its own read before the saved defaults become editable.
  const { data, error, isValidating, mutate } = useSWR(
    isGlobalHolder ? [SWR_KEYS.marketplace(marketplaceId), sessionId] : null,
    () => getMarketplace(marketplaceId),
    { revalidateOnMount: true, onErrorRetry: skipRetryOnAuthError }
  );
  const [snapshot, setSnapshot] = useState<Marketplace | null>(null);
  useEffect(() => {
    if (!snapshot && data && !error && !isValidating)
      setSnapshot(data.marketplace);
  }, [snapshot, data, error, isValidating]);

  if (snapshot && !snapshot.owner_user_id && isGlobalHolder) {
    return (
      <AccessForm
        snapshot={snapshot}
        onClose={onClose}
        onSaved={onSaved}
        loadFailed={!!error}
        refresh={() => void mutate()}
      />
    );
  }

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Modal.Content width="sm">
        <Modal.Header title={t("access.title")} onClose={onClose} />
        <Modal.Body>
          <Section height="auto" alignItems="start">
            <Text
              role={!isGlobalHolder || snapshot || error ? "alert" : "status"}
            >
              {t(
                !isGlobalHolder
                  ? "access.forbidden"
                  : snapshot
                    ? "access.companyOnly"
                    : error
                      ? "access.loadError"
                      : "access.loading"
              )}
            </Text>
            {!!error && isGlobalHolder && (
              <Button prominence="secondary" onClick={() => void mutate()}>
                {t("retry")}
              </Button>
            )}
          </Section>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}

interface AccessFormProps {
  snapshot: Marketplace;
  onClose: () => void;
  onSaved?: (marketplace: Marketplace) => void;
  loadFailed: boolean;
  refresh: () => void;
}

function AccessForm({
  snapshot,
  onClose,
  onSaved,
  loadFailed,
  refresh,
}: AccessFormProps) {
  const t = useTranslations("marketplaces");
  const skillLimit = useSkillLimitFeedback();
  const access = useCompanyMarketplaceAccess(marketplaceAccessDraft(snapshot));
  const cache = useSWRConfig();
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const pending = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  function close() {
    if (!pending.current) onClose();
  }

  async function save() {
    if (pending.current || !access.ready || loadFailed) return;
    pending.current = true;
    setSaving(true);
    setFailure(null);
    let saved: Marketplace;
    try {
      saved = await updateMarketplaceAccess({
        id: snapshot.id,
        access: access.draft,
      });
    } catch (error) {
      if (alive.current) {
        setFailure(
          skillLimit(error)?.description ??
            fetchErrorDetail(error) ??
            t("requestError")
        );
        setSaving(false);
        pending.current = false;
      }
      return;
    }
    void cache.mutate(SWR_KEYS.marketplaces);
    void cache.mutate(SWR_KEYS.marketplace(snapshot.id));
    if (alive.current) {
      onSaved?.(saved);
      onClose();
    }
  }

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <Modal.Content width="sm">
        <Modal.Header
          title={t("access.title")}
          description={snapshot.name}
          onClose={saving ? undefined : close}
        />
        <Modal.Body padding={2}>
          <InputPadder>
            <Section height="auto" alignItems="stretch">
              {loadFailed && (
                <Section height="auto" alignItems="start" gap={2}>
                  <Text role="alert">{t("access.loadError")}</Text>
                  <Button
                    prominence="secondary"
                    disabled={saving}
                    onClick={refresh}
                  >
                    {t("retry")}
                  </Button>
                </Section>
              )}
              <CompanyMarketplaceAccessControls
                access={access}
                disabled={saving || loadFailed}
              />
              {failure && (
                <Text role="alert" wordWrap="wrap-anywhere">
                  {failure}
                </Text>
              )}
            </Section>
          </InputPadder>
        </Modal.Body>
        <Modal.Footer wrap>
          <Button prominence="secondary" disabled={saving} onClick={close}>
            {t("cancel")}
          </Button>
          <Button
            disabled={saving || !access.ready || loadFailed}
            onClick={() => void save()}
          >
            {t(saving ? "working" : "access.save")}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
