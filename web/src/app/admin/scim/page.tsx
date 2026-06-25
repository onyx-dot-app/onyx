"use client";

import { useState } from "react";

import { SvgUserSync } from "@opal/icons";
import { useTranslation } from "react-i18next";
import { toast } from "@/hooks/useToast";
import { useScimToken } from "@/hooks/useScimToken";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { SettingsLayouts } from "@opal/layouts";
import Text from "@/refresh-components/texts/Text";
import { PageLoader } from "@/refresh-components/PageLoader";

import type { ScimTokenCreatedResponse, ScimModalView } from "./interfaces";
import { generateScimToken } from "./svc";
import ScimSyncCard from "./ScimSyncCard";
import ScimModal from "./ScimModal";

// ---------------------------------------------------------------------------
// SCIM Content
// ---------------------------------------------------------------------------

function ScimContent() {
  const { t } = useTranslation();
  const { data: token, error: tokenError, isLoading, mutate } = useScimToken();

  const modal = useCreateModal();

  const [modalView, setModalView] = useState<ScimModalView | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const hasToken = !!token;
  const isConnected = hasToken && token.last_used_at !== null;

  if (isLoading) {
    return <PageLoader />;
  }

  if (tokenError) {
    return (
      <Text as="p" text03>
        {t("admin.scim.load_status_failed")}
      </Text>
    );
  }

  // -----------------------------------------------------------------------
  // Handlers
  // -----------------------------------------------------------------------

  function openModal(view: ScimModalView) {
    setModalView(view);
    modal.toggle(true);
  }

  function closeModal() {
    modal.toggle(false);
    setModalView(null);
  }

  async function handleCreateToken() {
    setIsSubmitting(true);
    try {
      const response = await generateScimToken("default");
      if (!response.ok) {
        let detail: string;
        try {
          const body = await response.clone().json();
          detail = body.detail ?? JSON.stringify(body);
        } catch {
          detail = await response.text();
        }
        toast.error(t("admin.scim.generate_failed", { detail }));
        return;
      }
      const created: ScimTokenCreatedResponse = await response.json();
      await mutate();
      openModal({ kind: "token", rawToken: created.raw_token });
      if (hasToken) toast.success(t("admin.scim.token_regenerated"));
    } catch {
      toast.error(t("admin.scim.something_wrong"));
    } finally {
      setIsSubmitting(false);
    }
  }

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  return (
    <>
      <ScimSyncCard
        hasToken={hasToken}
        isConnected={isConnected}
        lastUsedAt={token?.last_used_at ?? null}
        idpDomain={token?.idp_domain ?? null}
        isSubmitting={isSubmitting}
        onGenerate={handleCreateToken}
        onRegenerate={() => openModal({ kind: "regenerate" })}
      />

      {modal.isOpen && modalView && (
        <modal.Provider>
          <ScimModal
            view={modalView}
            isSubmitting={isSubmitting}
            onRegenerate={handleCreateToken}
            onClose={closeModal}
          />
        </modal.Provider>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Page() {
  const { t } = useTranslation();
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgUserSync}
        title={t("admin.scim.page_title")}
        description={t("admin.scim.page_desc")}
        divider
      />
      <SettingsLayouts.Body>
        <ScimContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
