"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { SvgUserSync } from "@opal/icons";
import { toast } from "@/hooks/useToast";
import { useScimToken } from "@/hooks/useScimToken";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import Text from "@/refresh-components/texts/Text";
import { ThreeDotsLoader } from "@/components/Loading";

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

  // 404 means no active token — not an error
  const is404 =
    tokenError &&
    typeof tokenError === "object" &&
    "status" in tokenError &&
    (tokenError as { status: number }).status === 404;

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  if (tokenError && !is404) {
    return (
      <Text as="p" text03>
        {t("failedToLoadToken")}
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
        toast.error(t("failedToGenerate", { detail }));
        return;
      }
      const created: ScimTokenCreatedResponse = await response.json();
      await mutate();
      openModal({ kind: "token", rawToken: created.raw_token });
      if (hasToken) toast.success(t("tokenRegenerated"));
    } catch {
      toast.error(t("somethingWentWrong"));
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
        title={t("title")}
        description={t("description")}
        separator
      />
      <SettingsLayouts.Body>
        <ScimContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
