"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { SvgTrash } from "@opal/icons";
import { markdown } from "@opal/utils";
import { ConfirmationModalLayout, Section } from "@opal/layouts";
import { useModalClose } from "@opal/components";
import { toast } from "@opal/layouts";
import {
  clearTracingProviderSettings,
  deleteTracingProvider,
} from "@/lib/tracing/svc";
import type { TracingDisconnectTarget } from "@/lib/tracing/types";

export interface TracingDeleteModalProps {
  target: TracingDisconnectTarget;
  /**
   * Env vars also configure the provider: the delete keeps it switched off,
   * so the env config does not send traces again on its own.
   */
  envConfigured: boolean;
  onDeleted: () => Promise<void>;
}

/** Confirms deleting a disconnected provider's saved key and settings. */
export function TracingDeleteModal({
  target,
  envConfigured,
  onDeleted,
}: TracingDeleteModalProps) {
  const t = useTranslations("admin.tracing");
  const onClose = useModalClose();
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleDelete() {
    setIsSubmitting(true);
    try {
      await (envConfigured
        ? clearTracingProviderSettings(target.providerType)
        : deleteTracingProvider(target.providerType));
      onClose?.();
    } catch (error) {
      toast.error(
        error instanceof Error && error.message
          ? error.message
          : t("toasts.unexpectedError")
      );
    } finally {
      // Refresh regardless; swallow refresh errors so they can't misreport the
      // already-completed delete.
      await Promise.allSettled([onDeleted()]);
      setIsSubmitting(false);
    }
  }

  return (
    <ConfirmationModalLayout
      icon={SvgTrash}
      // A pending request keeps the modal open: its close would otherwise
      // close whichever modal is open when it finishes.
      onClose={isSubmitting ? undefined : onClose}
      title={t("deleteModal.title", { label: target.label })}
      description={t("deleteModal.description")}
      submit={
        <Button
          variant="danger"
          onClick={() => void handleDelete()}
          disabled={isSubmitting}
        >
          {t("deleteModal.submit.label")}
        </Button>
      }
    >
      <Section alignItems="start" gap={2}>
        <Text as="p" color="text-03">
          {markdown(
            t(envConfigured ? "deleteModal.envBody" : "deleteModal.body", {
              label: target.label,
            })
          )}
        </Text>
      </Section>
    </ConfirmationModalLayout>
  );
}
