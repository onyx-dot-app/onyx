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

  function close() {
    if (isBusy) return;
    setIsOpen(false);
    setIsDirty(false);
    setConfirmationOpen(false);
  }

  function dismiss() {
    if (isBusy) {
      return;
    }
    if (confirmationOpen) {
      setConfirmationOpen(false);
    } else if (isDirty) {
      setConfirmationOpen(true);
    } else {
      close();
    }
  }

  return {
    isOpen,
    confirmationOpen,
    open,
    close,
    dismiss,
    confirmDiscard: close,
    cancelDiscard: () => setConfirmationOpen(false),
    setBusy: setIsBusy,
    setDirty: setIsDirty,
  };
}
