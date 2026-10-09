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
import { disconnectTracingProvider } from "@/lib/tracing/svc";
import type { TracingDisconnectTarget } from "@/lib/tracing/types";

export interface TracingDisconnectModalProps {
  target: TracingDisconnectTarget;
  onDisconnected: () => Promise<void>;
}

export function TracingDisconnectModal({
  target,
  onDisconnected,
}: TracingDisconnectModalProps) {
  const t = useTranslations("admin.tracing");
  const onClose = useModalClose();
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleDisconnect() {
    setIsSubmitting(true);
    try {
      await disconnectTracingProvider(target.providerType, target.config);
      toast.success(t("toasts.disconnected", { label: target.label }));
      onClose?.();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("toasts.unexpectedError")
      );
    } finally {
      // Refresh regardless; swallow refresh errors so they can't misreport the
      // already-completed disconnect.
      await Promise.allSettled([onDisconnected()]);
      setIsSubmitting(false);
    }
  }

  return (
    <ConfirmationModalLayout
      icon={SvgUnplug}
      title={t("disconnectModal.title", { label: target.label })}
      description={t("disconnectModal.description")}
      submit={
        <Button
          variant="danger"
          onClick={() => void handleDisconnect()}
          disabled={isSubmitting}
        >
          {t("disconnectModal.submit.label")}
        </Button>
      }
    >
      <Section alignItems="start" gap={2}>
        <Text color="text-03">
          {markdown(t("disconnectModal.body", { label: target.label }))}
        </Text>
      </Section>
    </ConfirmationModalLayout>
  );
}
