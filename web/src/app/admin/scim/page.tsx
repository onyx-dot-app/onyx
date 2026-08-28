"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { SvgUserSync } from "@opal/icons";
import { useScimToken } from "@/hooks/useScimToken";
import { useCreateModal } from "@opal/components";
import { SettingsLayouts, toast } from "@opal/layouts";
import Text from "@/refresh-components/texts/Text";
import { PageLoader } from "@opal/layouts";

import type { ScimTokenCreatedResponse, ScimModalView } from "./interfaces";
import { generateScimToken } from "./svc";
import ScimSyncCard from "./ScimSyncCard";
import ScimModal from "./ScimModal";

// ---------------------------------------------------------------------------
// SCIM Content
// ---------------------------------------------------------------------------

function ScimContent() {
  const t = useTranslations("admin.scim");
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
        {t("loadFailed.error")}
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
        toast.error(t("toasts.generateFailed", { detail }));
        return;
      }
      const created: ScimTokenCreatedResponse = await response.json();
      await mutate();
      openModal({ kind: "token", rawToken: created.raw_token });
      if (hasToken) toast.success(t("toasts.regenerated"));
    } catch {
      toast.error(t("toasts.genericError"));
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
  const t = useTranslations("admin.scim");

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgUserSync}
        title={t("header.title")}
        description={t("header.description")}
        divider
      />
      <SettingsLayouts.Body>
        <ScimContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
