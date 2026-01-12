import React from "react";
import Button from "@/refresh-components/buttons/Button";
import type { IconProps } from "@opal/types";
import Modal from "@/refresh-components/Modal";
import { SvgLoader } from "@opal/icons";
export interface ProviderModalProps {
  // Modal configurations
  clickOutsideToClose?: boolean;

  // Base modal props
  open: boolean;
  onOpenChange: (open: boolean) => void;
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description?: string;
  className?: string;
  children?: React.ReactNode;

  // Footer props
  onSubmit?: () => void;
  submitDisabled?: boolean;
  isSubmitting?: boolean;
  submitLabel?: string;
  cancelLabel?: string;
}

export default function ProviderModal({
  open,
  onOpenChange,
  icon: icon,
  title,
  description,
  children,
  onSubmit,
  submitDisabled = false,
  isSubmitting = false,
  submitLabel = "Connect",
  cancelLabel = "Cancel",
}: ProviderModalProps) {
  const SpinningLoader: React.FunctionComponent<IconProps> = (props) => (
    <SvgLoader
      {...props}
      className={`${
        props.className ?? ""
      } h-3 w-3 stroke-text-inverted-04 animate-spin`}
    />
  );

  const handleOpenChange = (isOpen: boolean) => {
    if (!isOpen) {
      onOpenChange(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && onSubmit && !submitDisabled && !isSubmitting) {
      // Check if the target is not a textarea (allow Enter in textareas)
      if ((e.target as HTMLElement).tagName !== "TEXTAREA") {
        e.preventDefault();
        onSubmit();
      }
    }
  };

  return (
    <Modal open={open} onOpenChange={handleOpenChange}>
      <Modal.Content tall onKeyDown={handleKeyDown}>
        <Modal.Header
          icon={icon}
          title={title}
          description={description}
          onClose={() => onOpenChange(false)}
        />

        <Modal.Body>{children}</Modal.Body>

        {onSubmit && (
          <Modal.Footer>
            <Button type="button" secondary onClick={() => onOpenChange(false)}>
              {cancelLabel}
            </Button>
            <Button
              type="button"
              onClick={onSubmit}
              disabled={submitDisabled || isSubmitting}
              leftIcon={isSubmitting ? SpinningLoader : undefined}
            >
              {submitLabel}
            </Button>
          </Modal.Footer>
        )}
      </Modal.Content>
    </Modal>
  );
}
