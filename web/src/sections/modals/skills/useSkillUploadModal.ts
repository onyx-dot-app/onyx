"use client";

import { useState } from "react";

export default function useSkillUploadModal() {
  const [isOpen, setIsOpen] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [confirmationOpen, setConfirmationOpen] = useState(false);

  function open() {
    setIsOpen(true);
  }

  function discardAndClose() {
    if (isBusy) return;
    setIsOpen(false);
    setIsDirty(false);
    setConfirmationOpen(false);
  }

  function requestDismiss() {
    if (isBusy) {
      return;
    }
    if (confirmationOpen) {
      setConfirmationOpen(false);
    } else if (isDirty) {
      setConfirmationOpen(true);
    } else {
      discardAndClose();
    }
  }

  return {
    isOpen,
    confirmationOpen,
    open,
    requestDismiss,
    discardAndClose,
    cancelDiscard: () => setConfirmationOpen(false),
    setBusy: setIsBusy,
    setDirty: setIsDirty,
  };
}
