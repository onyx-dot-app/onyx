"use client";

import React from "react";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { Button, Modal, Text } from "@opal/components";
import { useModalClose } from "@opal/components/modal/context";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ConfirmationModalProps {
  icon: IconFunctionComponent;
  title: string | RichStr;
  description?: string | RichStr;

  /** Body content. Plain strings render as `text-03` body copy. */
  children?: React.ReactNode;

  /** The confirm action, rendered in the footer after Cancel unless `hideCancel`. */
  submit: React.ReactNode;

  hideCancel?: boolean;

  /** Runs when the modal closes (composed via `useModalClose`). */
  onClose?: () => void;

  /** Gray body background separating it from the header and footer. */
  twoTone?: boolean;
}

// ---------------------------------------------------------------------------
// ConfirmationModalLayout
// ---------------------------------------------------------------------------

/**
 * Prebuilt small confirm dialog on `Modal`: icon header, body, Cancel plus
 * a caller-supplied submit action. Renders open, so mount it inside the
 * `Provider` from `useCreateModal` (closing goes through `useModalClose`).
 */
function ConfirmationModalLayout({
  icon,
  title,
  description,
  children,
  submit,
  hideCancel,
  onClose: externalOnClose,
  twoTone = true,
}: ConfirmationModalProps) {
  const modalClose = useModalClose(externalOnClose);
  const closedRef = React.useRef(false);

  // The header X sits inside DialogPrimitive.Close AND carries onClick, so
  // one click reaches here twice (directly and via onOpenChange). A closed
  // confirmation unmounts, so close is one-shot by definition.
  const onClose = () => {
    if (closedRef.current) return;
    closedRef.current = true;
    modalClose?.();
  };

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={icon}
          title={title}
          description={description}
          onClose={onClose}
        />
        <Modal.Body twoTone={twoTone}>
          {typeof children === "string" ? (
            <Text as="p" color="text-03">
              {children}
            </Text>
          ) : (
            children
          )}
        </Modal.Body>
        <Modal.Footer>
          {!hideCancel && (
            <Button prominence="secondary" onClick={onClose}>
              Cancel
            </Button>
          )}
          {submit}
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}

export { ConfirmationModalLayout, type ConfirmationModalProps };
