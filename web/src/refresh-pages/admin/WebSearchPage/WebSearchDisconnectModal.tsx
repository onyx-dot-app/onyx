"use client";

import { useState } from "react";
import { Button, Text } from "@opal/components";
import { SvgUnplug } from "@opal/icons";
import { markdown } from "@opal/utils";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { useModalClose } from "@/refresh-components/contexts/ModalContext";
import { toast } from "@/hooks/useToast";
import { useWebSearchProviders } from "@/lib/webSearch/hooks";
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
  const isExa = disconnectTarget.providerType === "exa";

  const isActive = isSearch
    ? searchProviders.find((p) => p.id === disconnectTarget.id)?.is_active ??
      false
    : contentProviders.find((p) => p.id === disconnectTarget.id)?.is_active ??
      false;

  const siblingCategory = isSearch ? "content" : "search";
  const exaSibling = isExa
    ? isSearch
      ? contentProviders.find((p) => p.provider_type === "exa" && p.id > 0)
      : searchProviders.find((p) => p.provider_type === "exa" && p.id > 0)
    : undefined;

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
      if (exaSibling) {
        await disconnectProvider(exaSibling.id, siblingCategory, null);
      }
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
      title={`Disconnect ${disconnectTarget.label}`}
      description="This will remove the stored credentials for this provider."
      submit={
        <Button
          variant="danger"
          onClick={() => void handleDisconnect()}
          disabled={isSubmitting}
        >
          Disconnect
        </Button>
      }
    >
      {isExa ? (
        <Text as="p" font="main-ui-body" color="text-03">
          Both the Exa search engine and web crawler will be disconnected.
        </Text>
      ) : isActive ? (
        <Text as="p" font="main-ui-body" color="text-03">
          {markdown(
            `**${disconnectTarget.label}** is the active ${categoryLabel}. ${
              featureLabel.charAt(0).toUpperCase() + featureLabel.slice(1)
            } history will be preserved.`
          )}
        </Text>
      ) : null}
    </ConfirmationModalLayout>
  );
}
