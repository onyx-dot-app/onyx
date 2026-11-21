"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { SvgTrash } from "@opal/icons";
import { markdown } from "@opal/utils";
import { ConfirmationModalLayout, Section } from "@opal/layouts";
import { useModalClose } from "@opal/components";
import { toast } from "@opal/layouts";
import { deleteTracingProvider } from "@/lib/tracing/svc";
import type { TracingDisconnectTarget } from "@/lib/tracing/types";

export interface TracingDeleteModalProps {
  target: TracingDisconnectTarget;
  onDeleted: () => Promise<void>;
}

/** Confirms deleting a disconnected provider's saved key and settings. */
export function TracingDeleteModal({
  target,
  onDeleted,
}: TracingDeleteModalProps) {
  const t = useTranslations("admin.tracing");
  const onClose = useModalClose();
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleDelete() {
    setIsSubmitting(true);
    try {
      await deleteTracingProvider(target.providerType);
      onClose?.();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("toasts.unexpectedError")
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
        <Text color="text-03">
          {markdown(t("deleteModal.body", { label: target.label }))}
        </Text>
      </Section>
    </ConfirmationModalLayout>
  );
}
