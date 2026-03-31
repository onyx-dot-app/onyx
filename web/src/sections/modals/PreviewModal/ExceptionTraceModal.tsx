import Modal from "@/refresh-components/Modal";
import { SvgAlertTriangle } from "@opal/icons";
import { CodePreview } from "@/sections/modals/PreviewModal/variants/CodePreview";
import { CopyButton } from "@/sections/modals/PreviewModal/variants/shared";
import FloatingFooter from "@/sections/modals/PreviewModal/FloatingFooter";

interface ExceptionTraceModalProps {
  onOutsideClick: () => void;
  exceptionTrace: string;
  language?: string;
}

export default function ExceptionTraceModal({
  onOutsideClick,
  exceptionTrace,
  language = "python",
}: ExceptionTraceModalProps) {
  return (
    <Modal open onOpenChange={onOutsideClick}>
      <Modal.Content width="full" height="full">
        <Modal.Header
          icon={SvgAlertTriangle}
          title="Full Exception Trace"
          onClose={onOutsideClick}
          height="fit"
        />

        <div className="flex flex-col flex-1 min-h-0 overflow-hidden w-full bg-background-tint-01">
          <CodePreview content={exceptionTrace} language={language} normalize />
        </div>

        <FloatingFooter
          right={<CopyButton getText={() => exceptionTrace} />}
          codeBackground
        />
      </Modal.Content>
    </Modal>
  );
}
