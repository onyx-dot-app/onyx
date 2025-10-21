"use client";

import React, { useState } from "react";
import { handleEnterPress, useEscapePress } from "@/lib/typingUtils";
import { UNNAMED_CHAT } from "@/lib/constants";

interface ButtonRenamingProps {
  initialName: string | null;
  onRename: (newName: string) => Promise<void>;
  onClose: () => void;
}

export default function ButtonRenaming({
  initialName,
  onRename,
  onClose,
}: ButtonRenamingProps) {
  const [renamingValue, setRenamingValue] = useState(
    initialName || UNNAMED_CHAT
  );

  useEscapePress(onClose, true);

  async function submitRename() {
    const newName = renamingValue.trim();
    if (newName === "" || newName === initialName) {
      onClose();
      return;
    }

    // Close immediately for instant feedback
    onClose();

    // Proceed with the rename operation after closing
    try {
      await onRename(newName);
    } catch (error) {
      console.error("Failed to rename:", error);
    }
  }

  return (
    <input
      onBlur={onClose}
      value={renamingValue}
      className="bg-transparent outline-none resize-none overflow-x-hidden overflow-y-hidden whitespace-nowrap no-scrollbar font-main-content-body w-full"
      onChange={(event) => setRenamingValue(event.target.value)}
      onKeyDown={handleEnterPress(() => submitRename())}
      autoFocus
    />
  );
}
