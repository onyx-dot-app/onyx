"use client";

import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { BasicModalFooter, Modal } from "@opal/components";

interface MCPFormActionsProps {
  variant: "modal" | "page";
  active: boolean;
  footerTarget: HTMLDivElement | null;
  submit: ReactNode;
  cancel?: ReactNode;
  back?: ReactNode;
}

export default function MCPFormActions({
  variant,
  active,
  footerTarget,
  submit,
  cancel,
  back,
}: MCPFormActionsProps) {
  if (!active) return null;
  if (variant === "page" && footerTarget) {
    return createPortal(
      <div className="flex items-center gap-2">{submit}</div>,
      footerTarget
    );
  }
  if (variant === "page") {
    return (
      <div className="flex w-full min-w-0 flex-wrap items-center justify-between gap-3 border-t border-border-01 pt-5">
        <div className="ms-auto flex flex-wrap items-center gap-3">
          {submit}
        </div>
      </div>
    );
  }
  return footerTarget
    ? createPortal(
        <Modal.Footer padding={6} wrap>
          <BasicModalFooter
            stackOnSmallScreens
            left={back}
            cancel={cancel}
            submit={submit}
          />
        </Modal.Footer>,
        footerTarget
      )
    : null;
}
