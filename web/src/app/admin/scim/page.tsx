"use client";

import { useState } from "react";

import { SvgUserSync } from "@opal/icons";
import { toast } from "@/hooks/useToast";
import { useScimToken } from "@/hooks/useScimToken";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import * as SettingsLayouts from "@/layouts/settings-layouts";
// TODO(@raunakab): migrate this `refresh-components/Text` to `@opal/components` Text
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
        Failed to load SCIM token status.
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
        toast.error(`Failed to generate token: ${detail}`);
        return;
      }
      const created: ScimTokenCreatedResponse = await response.json();
      await mutate();
      openModal({ kind: "token", rawToken: created.raw_token });
      if (hasToken) toast.success("Token regenerated");
    } catch {
      toast.error("Something went wrong. Please try again.");
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
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgUserSync}
        title="SCIM"
        description="Sync users and groups via System for Cross-domain Identity Management (SCIM) protocol."
        separator
      />
      <SettingsLayouts.Body>
        <ScimContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
