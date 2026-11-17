"use client";

import React from "react";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import type { ContentColor } from "@opal/layouts/content/components";
import { Button, Modal, Text } from "@opal/components";
import { useModalClose } from "@opal/components/modal/context";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ConfirmationModalProps {
  icon: IconFunctionComponent;
  /** Colour mode of the header icon and title, as on `Content`. */
  color?: ContentColor;
  title: string | RichStr;
  description?: string | RichStr;

  /** Body content. Plain strings render as `text-03` body copy. */
  children?: React.ReactNode;

  /** The confirm action, rendered in the footer after Cancel unless `hideCancel`. */
  submit: React.ReactNode;

  hideCancel?: boolean;

  /**
   * Closes the modal. When passed, the caller owns closing, so it can refuse
   * (e.g. while a request runs); `undefined` hides Cancel and the X. When
   * omitted, the `useCreateModal` owner closes it.
   */
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
 * `Provider` from `useCreateModal`; closing goes through `onClose`, or the
 * owner when `onClose` is omitted.
 */
function ConfirmationModalLayout(props: ConfirmationModalProps) {
  const {
    icon,
    color,
    title,
    description,
    children,
    submit,
    hideCancel,
    onClose: externalOnClose,
    twoTone = true,
  } = props;
  const ownerClose = useModalClose();
  // `onClose={undefined}` (e.g. while busy) means "not closable", so only an
  // omitted prop falls back to the owner.
  const close = "onClose" in props ? externalOnClose : ownerClose;
  const closingRef = React.useRef(false);
  const canClose = close !== undefined;

  // The header X sits inside DialogPrimitive.Close AND carries onClick, so
  // one click reaches here twice (directly and via onOpenChange). Dedupe
  // within that event only, so a close the caller declined can be retried.
  const onClose = () => {
    if (!close || closingRef.current) return;
    closingRef.current = true;
    queueMicrotask(() => {
      closingRef.current = false;
    });
    close();
  };

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={icon}
          color={color}
          title={title}
          description={description}
          onClose={canClose ? onClose : undefined}
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
          {!hideCancel && canClose && (
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
