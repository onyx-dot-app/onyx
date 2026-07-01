"use client";

import { useState } from "react";
import { Button, Text } from "@opal/components";
import { SvgUnplug } from "@opal/icons";
import { markdown } from "@opal/utils";
import { Section } from "@/layouts/general-layouts";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { useModalClose } from "@/refresh-components/contexts/ModalContext";
import { toast } from "@/hooks/useToast";
import { disconnectTracingProvider } from "@/lib/tracing/svc";
import type { TracingDisconnectTarget } from "@/lib/tracing/types";

export interface TracingDisconnectModalProps {
  target: TracingDisconnectTarget;
  onDisconnected: () => Promise<unknown>;
}

export function TracingDisconnectModal({
  target,
  onDisconnected,
}: TracingDisconnectModalProps) {
  const onClose = useModalClose();
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleDisconnect() {
    setIsSubmitting(true);
    try {
      await disconnectTracingProvider(target.providerType, target.config);
      toast.success(`${target.label} disconnected`);
      onClose?.();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Unexpected error occurred."
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
      title={`Disconnect ${target.label}`}
      description="Stop sending LLM call traces to this provider."
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
        <Text color="text-03">
          {markdown(
            `LLM call traces will no longer be sent to **${target.label}**. Traces already sent are unaffected.`
          )}
        </Text>
      </Section>
    </ConfirmationModalLayout>
  );
}
