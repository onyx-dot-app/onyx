"use client";

import { useState } from "react";
import { Button, useModalClose } from "@opal/components";
import { ConfirmationModalLayout, toast } from "@opal/layouts";
import type { IconFunctionComponent } from "@opal/types";

interface IntegrationConfirmModalProps {
  icon: IconFunctionComponent;
  title: string;
  description?: string;
  /** What the action does, above the buttons. */
  children: React.ReactNode;
  submitLabel: string;
  /** Runs the action. A thrown error is toasted, and the modal stays open. */
  onConfirm: () => Promise<void>;
  /** Toasted for a thrown value that is not an `Error`. */
  errorMessage: string;
  /** Runs after the action, whether or not it succeeded (e.g. a refetch). */
  onSettled?: () => Promise<void>;
}

/**
 * Confirms a destructive `IntegrationCard` action, such as disconnect or
 * delete. Render it inside the modal's provider (`useCreateModal`).
 */
function IntegrationConfirmModal({
  icon,
  title,
  description,
  children,
  submitLabel,
  onConfirm,
  errorMessage,
  onSettled,
}: IntegrationConfirmModalProps) {
  const onClose = useModalClose();
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleConfirm() {
    setIsSubmitting(true);
    try {
      await onConfirm();
      onClose?.();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : errorMessage);
    } finally {
      // A failed refetch must not report the completed action as failed.
      if (onSettled) await Promise.allSettled([onSettled()]);
      setIsSubmitting(false);
    }
  }

  return (
    <ConfirmationModalLayout
      icon={icon}
      title={title}
      description={description}
      submit={
        <Button
          variant="danger"
          onClick={() => void handleConfirm()}
          disabled={isSubmitting}
        >
          {submitLabel}
        </Button>
      }
    >
      {children}
    </ConfirmationModalLayout>
  );
}

export { IntegrationConfirmModal, type IntegrationConfirmModalProps };
