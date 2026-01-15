import { useState } from "react";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { SvgAlertTriangle, SvgCheck, SvgCopy } from "@opal/icons";

interface ExceptionTraceModalProps {
  onOutsideClick: () => void;
  exceptionTrace: string;
}

export default function ExceptionTraceModal({
  onOutsideClick,
  exceptionTrace,
}: ExceptionTraceModalProps) {
  const [copyClicked, setCopyClicked] = useState(false);

  return (
    <Modal open onOpenChange={onOutsideClick}>
      <Modal.Content large>
        <Modal.Header
          icon={SvgAlertTriangle}
          title="Full Exception Trace"
          onClose={onOutsideClick}
        />
        <Modal.Body>
          <div className="mb-6">
            {!copyClicked ? (
              <button
                type="button"
                onClick={() => {
                  navigator.clipboard.writeText(exceptionTrace!);
                  setCopyClicked(true);
                  setTimeout(() => setCopyClicked(false), 2000);
                }}
                className="flex w-fit items-center hover:bg-accent-background p-2 border-border border rounded"
              >
                <Text as="span">Copy full trace</Text>
                <SvgCopy className="stroke-text-04 ml-2 h-4 w-4 flex flex-shrink-0" />
              </button>
            ) : (
              <div className="flex w-fit items-center hover:bg-accent-background p-2 border-border border rounded cursor-default">
                <Text as="span">Copied to clipboard</Text>
                <SvgCheck className="stroke-text-04 my-auto ml-2 h-4 w-4 flex flex-shrink-0" />
              </div>
            )}
          </div>
          <div className="whitespace-pre-wrap">{exceptionTrace}</div>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
