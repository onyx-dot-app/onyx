"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { SvgUnplug } from "@opal/icons";
import { markdown } from "@opal/utils";
import { Section } from "@/layouts/general-layouts";
import { ConfirmationModalLayout } from "@opal/layouts";
import { useModalClose } from "@opal/components";
import { toast } from "@opal/layouts";
import { useWebSearchProviders } from "@/lib/webSearch/hooks";
import { disconnectProvider } from "@/lib/webSearch/svc";
import type { DisconnectTargetState } from "@/lib/webSearch/types";

interface WebSearchDisconnectModalProps {
  disconnectTarget: DisconnectTargetState;
}

export function WebSearchDisconnectModal({
  disconnectTarget,
}: WebSearchDisconnectModalProps) {
  const t = useTranslations("admin.webSearch");
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
      toast.success(
        t("disconnectModal.disconnectSuccess.message", {
          label: disconnectTarget.label,
        })
      );
      onClose?.();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("unexpectedError.message");
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
      title={t("disconnectModal.header.title", {
        label: disconnectTarget.label,
      })}
      description={t("disconnectModal.header.description")}
      submit={
        <Button
          variant="danger"
          onClick={() => void handleDisconnect()}
          disabled={isSubmitting}
        >
          {t("disconnectModal.submitButton.label")}
        </Button>
      }
    >
      <Section alignItems="start" gap={2}>
        {isSearch ? (
          <>
            <Text color="text-03">
              {markdown(
                t("disconnectModal.search.description", {
                  label: disconnectTarget.label,
                })
              )}
            </Text>
            {!hasAnotherProvider && (
              <Text color="text-03">
                {t("disconnectModal.connectAnother.description")}
              </Text>
            )}
          </>
        ) : (
          <>
            <Text color="text-03">
              {markdown(
                t("disconnectModal.content.description", {
                  label: disconnectTarget.label,
                })
              )}
            </Text>
            {!hasAnotherProvider && (
              <Text color="text-03">
                {t("disconnectModal.fallback.description")}
              </Text>
            )}
          </>
        )}
      </Section>
    </ConfirmationModalLayout>
  );
}
