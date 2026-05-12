"use client";

import { useState } from "react";
import { Button, Text } from "@opal/components";
import { SvgUnplug } from "@opal/icons";
import { markdown } from "@opal/utils";
import { Section } from "@/layouts/general-layouts";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { useModalClose } from "@/refresh-components/contexts/ModalContext";
import { toast } from "@/hooks/useToast";
import { useWebSearchProviders } from "@/lib/webSearch/hooks";
import {
  isSearchProviderConfigured,
  isContentProviderConfigured,
} from "@/lib/webSearch/utils";
import { disconnectProvider } from "@/lib/webSearch/svc";
import type { DisconnectTargetState } from "@/lib/webSearch/types";

interface WebSearchDisconnectModalProps {
  disconnectTarget: DisconnectTargetState;
}

export function WebSearchDisconnectModal({
  disconnectTarget,
}: WebSearchDisconnectModalProps) {
  const onClose = useModalClose();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const {
    searchProviders,
    contentProviders,
    mutateSearchProviders,
    mutateContentProviders,
  } = useWebSearchProviders();

  const isSearch = disconnectTarget.category === "search";

  const isActive = isSearch
    ? searchProviders.find((p) => p.id === disconnectTarget.id)?.is_active ??
      false
    : contentProviders.find((p) => p.id === disconnectTarget.id)?.is_active ??
      false;

  const otherConfigured = isSearch
    ? searchProviders.filter(
        (p) =>
          p.id !== disconnectTarget.id &&
          p.id > 0 &&
          isSearchProviderConfigured(p.provider_type, p)
      )
    : contentProviders.filter(
        (p) =>
          p.id !== disconnectTarget.id &&
          p.provider_type !== "onyx_web_crawler" &&
          p.id > 0 &&
          isContentProviderConfigured(p.provider_type, p)
      );

  const isBlocked = isActive && otherConfigured.length > 0;
  const categoryLabel = isSearch ? "search engine" : "web crawler";
  const featureLabel = isSearch ? "web search" : "web crawling";

  async function handleDisconnect() {
    setIsSubmitting(true);
    try {
      await disconnectProvider(
        disconnectTarget.id,
        disconnectTarget.category,
        null
      );
      toast.success(`${disconnectTarget.label} disconnected`);
      await mutateSearchProviders();
      await mutateContentProviders();
      onClose?.();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unexpected error occurred.";
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <ConfirmationModalLayout
      icon={SvgUnplug}
      title={markdown(`Disconnect *${disconnectTarget.label}*`)}
      description="This will remove the stored credentials for this provider."
      submit={
        <Button
          variant="danger"
          onClick={() => void handleDisconnect()}
          disabled={isBlocked || isSubmitting}
        >
          Disconnect
        </Button>
      }
    >
      <Section alignItems="start" gap={0.5}>
        {isBlocked ? (
          <Text as="p" font="main-ui-body" color="text-03">
            {markdown(
              `**${disconnectTarget.label}** is the active ${categoryLabel}. Set another ${categoryLabel} as active before disconnecting.`
            )}
          </Text>
        ) : isActive ? (
          <>
            <Text as="p" font="main-ui-body" color="text-03">
              {markdown(
                `**${disconnectTarget.label}** is the active ${categoryLabel}.`
              )}
            </Text>
            <Text as="p" font="main-ui-body" color="text-03">
              {`Disconnecting will disable ${featureLabel}.`}
            </Text>
          </>
        ) : (
          <Text as="p" font="main-ui-body" color="text-03">
            {markdown(
              `${
                isSearch ? "Web search" : "Web crawling"
              } will no longer be routed through **${disconnectTarget.label}**.`
            )}
          </Text>
        )}
      </Section>
    </ConfirmationModalLayout>
  );
}
