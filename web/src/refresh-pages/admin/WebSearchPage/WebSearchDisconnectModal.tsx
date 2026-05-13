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
  const hasAnotherProvider = isSearch
    ? searchProviders.some(
        (p) => p.masked_api_key && p.id !== disconnectTarget.id
      )
    : contentProviders.some(
        (p) => p.masked_api_key && p.id !== disconnectTarget.id
      );

  const siblingCategory = isSearch ? "content" : "search";
  const exaSibling =
    disconnectTarget.providerType === "exa"
      ? isSearch
        ? contentProviders.find((p) => p.provider_type === "exa" && p.id > 0)
        : searchProviders.find((p) => p.provider_type === "exa" && p.id > 0)
      : undefined;

  async function handleDisconnect() {
    setIsSubmitting(true);
    try {
      await disconnectProvider(disconnectTarget.id, disconnectTarget.category);
      if (exaSibling) {
        await disconnectProvider(exaSibling.id, siblingCategory);
      }
      toast.success(`${disconnectTarget.label} disconnected`);
      onClose?.();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unexpected error occurred.";
      toast.error(message);
    } finally {
      await Promise.allSettled([
        mutateSearchProviders(),
        mutateContentProviders(),
      ]);
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
      <Section alignItems="start" gap={0.5}>
        {isSearch ? (
          <>
            <Text color="text-03">
              {markdown(
                `Web search will no longer be routed through **${disconnectTarget.label}**. Search history will be preserved.`
              )}
            </Text>
            {!hasAnotherProvider && (
              <Text color="text-03">
                Connect another search engine to continue to use web search.
              </Text>
            )}
          </>
        ) : (
          <>
            <Text color="text-03">
              {markdown(
                `**${disconnectTarget.label}** will no longer be used to read search result web pages.`
              )}
            </Text>
            {!hasAnotherProvider && (
              <Text color="text-03">
                Onyx will fall back to the built-in web crawler.
              </Text>
            )}
          </>
        )}
      </Section>
    </ConfirmationModalLayout>
  );
}
