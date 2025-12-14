import { useState } from "react";
import Modal from "@/refresh-components/Modal";
import SvgAlertTriangle from "@/icons/alert-triangle";
import SvgCopy from "@/icons/copy";
import SvgCheck from "@/icons/check";

export default function ExceptionTraceModal({
  onOutsideClick,
  exceptionTrace,
}: {
  onOutsideClick: () => void;
  exceptionTrace: string;
}) {
  const [copyClicked, setCopyClicked] = useState(false);

  return (
    <Modal open onOpenChange={onOutsideClick}>
      <Modal.Content large>
        <Modal.Header
          icon={SvgAlertTriangle}
          title="Full Exception Trace"
          onClose={onOutsideClick}
        />
        <Modal.Body className="overflow-y-auto overflow-x-hidden pr-3 max-h-[70vh]">
          <div className="mb-6">
            {!copyClicked ? (
              <div
                onClick={() => {
                  navigator.clipboard.writeText(exceptionTrace!);
                  setCopyClicked(true);
                  setTimeout(() => setCopyClicked(false), 2000);
                }}
                className="flex w-fit cursor-pointer hover:bg-accent-background p-2 border-border border rounded"
              >
                Copy full trace
                <SvgCopy className="stroke-text-04 ml-2 my-auto" />
              </div>
            ) : (
              <div className="flex w-fit hover:bg-accent-background p-2 border-border border rounded cursor-default">
                Copied to clipboard
                <SvgCheck
                  className="my-auto ml-2 flex flex-shrink-0"
                  size={16}
                />
              </div>
            )}
          </div>
          <div className="whitespace-pre-wrap">{exceptionTrace}</div>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
