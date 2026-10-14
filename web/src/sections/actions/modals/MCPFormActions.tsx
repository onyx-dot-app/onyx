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
  leading?: ReactNode;
}

export default function MCPFormActions({
  variant,
  active,
  footerTarget,
  submit,
  cancel,
  back,
  leading,
}: MCPFormActionsProps) {
  if (!active) return null;
  if (variant === "page") {
    return (
      <div className="flex w-full min-w-0 flex-wrap items-center justify-between gap-3 border-t border-border-01 pt-5">
        {leading}
        <div className="ms-auto">{submit}</div>
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
